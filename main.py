"""
FastAPI application for managing Orders of Service (OS) with QR Codes.

Ported from Flask to FastAPI. Supports SQLite (local) and PostgreSQL (Supabase).
"""

import csv
import io
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base

try:
    import qrcode
except ImportError:
    qrcode = None

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:8000').rstrip('/')

# Database setup
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///os.db')
# Supabase / Heroku may provide postgres://, SQLAlchemy requires postgresql://
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)

engine_kwargs: dict = {}
if not _db_url.startswith('sqlite'):
    # Supabase / serverless-friendly engine options.
    # prepare_threshold=None disables server-side prepared statements, required
    # when using Supabase's transaction-mode connection pooler (port 6543).
    engine_kwargs = {
        'pool_pre_ping': True,
        'pool_size': 1,
        'max_overflow': 0,
        'pool_recycle': 300,
        'connect_args': {
            'sslmode': 'require',
            'prepare_threshold': None,
        },
    }

engine = create_engine(_db_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Order(Base):
    """Represents an order of service entry."""
    __tablename__ = 'order'

    id = Column(Integer, primary_key=True)
    token = Column(String(64), unique=True, nullable=False)
    cliente = Column(String(120), nullable=False)
    contato = Column(String(120), nullable=False)
    produto = Column(String(120), nullable=False)
    problema = Column(Text, nullable=False)
    status = Column(String(50), default='Recebido', nullable=False)
    data_entrada = Column(DateTime, default=datetime.utcnow)

    def qr_code_url(self) -> str:
        """Return the URL for the QR code image (generated on-the-fly)."""
        return f"/qr/{self.token}.png"


# Create tables at import time so Vercel's serverless runtime creates them
# on first cold start without needing a separate migration step.
# Wrapped in try/except so a DB connectivity issue doesn't crash startup outright.
try:
    Base.metadata.create_all(engine)
except Exception as _create_err:
    import warnings
    warnings.warn(f"Could not create tables on startup: {_create_err}")

COLOR_MAP = {
    'Recebido': '#28a745',
    'Em análise': '#ffc107',
    'Aguardando aprovação': '#fd7e14',
    'Em execução': '#d63384',
    'Pronto': '#0d6efd',
}

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Inovatech OS")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get('SECRET_KEY', 'dev-only-insecure-key'),
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order_to_dict(order: Order) -> dict:
    return {
        'id': order.id,
        'token': order.token,
        'cliente': order.cliente,
        'contato': order.contato,
        'produto': order.produto,
        'problema': order.problema,
        'status': order.status,
        'data_entrada': order.data_entrada.isoformat(),
    }


def _filtered_query(db, status: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None):
    """Return an Order query filtered by the given params."""
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    if start:
        q = q.filter(func.date(Order.data_entrada) >= start)
    if end:
        q = q.filter(func.date(Order.data_entrada) <= end)
    return q


def _flash(request: Request, message: str, category: str = 'info') -> None:
    messages = request.session.get('flash', [])
    messages.append({'category': category, 'message': message})
    request.session['flash'] = messages


def _pop_flash(request: Request) -> list:
    messages = request.session.get('flash', [])
    request.session['flash'] = []
    return messages


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

@app.get('/', response_class=HTMLResponse, name='index')
def index(request: Request, status: str = '', start: str = '', end: str = ''):
    """Display a list of all orders with optional status/date filters."""
    db = SessionLocal()
    try:
        q = _filtered_query(db, status or None, start or None, end or None)
        orders = q.order_by(Order.data_entrada.desc()).all()
        # Build export URL with same filters
        params = []
        if status:
            params.append(f'status={status}')
        if start:
            params.append(f'start={start}')
        if end:
            params.append(f'end={end}')
        qs = ('?' + '&'.join(params)) if params else ''
        return templates.TemplateResponse(request, 'list_os.html', {
            'orders': orders,
            'color_map': COLOR_MAP,
            'status_filter': status,
            'date_from': start,
            'date_to': end,
            'export_url': f'/export{qs}',
            'messages': _pop_flash(request),
        })
    finally:
        db.close()


@app.get('/new', response_class=HTMLResponse, name='new_order')
def new_order(request: Request):
    """Render the new order form."""
    return templates.TemplateResponse(request, 'new_os.html', {
        'statuses': list(COLOR_MAP.keys()),
        'messages': _pop_flash(request),
    })


@app.get('/os/{token}', response_class=HTMLResponse, name='order_detail')
def order_detail(token: str, request: Request):
    """Show the details of a single order using its unique token."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(token=token).first()
        if not order:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(request, 'os_detail.html', {
            'order': order,
            'statuses': list(COLOR_MAP.keys()),
            'messages': _pop_flash(request),
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get('/export', name='export_orders')
def export_orders(status: str = '', start: str = '', end: str = ''):
    """Export orders as CSV, respecting the same filters as the list view."""
    db = SessionLocal()
    try:
        q = _filtered_query(db, status or None, start or None, end or None)
        orders = q.order_by(Order.data_entrada.desc()).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['id', 'token', 'cliente', 'contato', 'produto', 'problema', 'status', 'data_entrada'])
        for o in orders:
            writer.writerow([
                o.id, o.token, o.cliente, o.contato,
                o.produto, o.problema, o.status,
                o.data_entrada.isoformat(),
            ])
        return Response(
            content=output.getvalue(),
            media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename=ordens_servico.csv'},
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get('/api/orders', name='api_list_orders')
def api_list_orders(status: str = '', start: str = '', end: str = ''):
    """Return all orders (with optional filters) as JSON."""
    db = SessionLocal()
    try:
        q = _filtered_query(db, status or None, start or None, end or None)
        orders = q.order_by(Order.data_entrada.desc()).all()
        return {'orders': [_order_to_dict(o) for o in orders]}
    finally:
        db.close()


@app.get('/api/orders/{token}', name='api_get_order')
def api_get_order(token: str):
    """Return a single order by token as JSON."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(token=token).first()
        if not order:
            raise HTTPException(status_code=404, detail='not_found')
        return _order_to_dict(order)
    finally:
        db.close()


@app.post('/api/orders', name='api_create_order')
async def api_create_order(request: Request):
    """Create a new order via JSON or form data.

    JSON callers receive a 201 response with the created order.
    Browser form submissions are redirected to the index page.
    """
    content_type = request.headers.get('content-type', '')
    is_json = 'application/json' in content_type

    if is_json:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    cliente = (data.get('cliente') or '').strip()
    contato = (data.get('contato') or '').strip()
    produto = (data.get('produto') or '').strip()
    problema = (data.get('problema') or '').strip()
    status_val = (data.get('status') or 'Recebido').strip() or 'Recebido'

    if not (cliente and contato and produto and problema):
        if is_json:
            raise HTTPException(status_code=400, detail='missing_fields')
        _flash(request, 'Todos os campos são obrigatórios.', 'danger')
        return templates.TemplateResponse(request, 'new_os.html', {
            'statuses': list(COLOR_MAP.keys()),
            'messages': _pop_flash(request),
        }, status_code=422)

    token = uuid.uuid4().hex
    db = SessionLocal()
    try:
        order = Order(
            token=token, cliente=cliente, contato=contato,
            produto=produto, problema=problema, status=status_val,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        if is_json:
            return JSONResponse(_order_to_dict(order), status_code=201)
        _flash(request, 'Ordem criada com sucesso! Etiqueta com QR gerada.', 'success')
        return RedirectResponse(url='/', status_code=303)
    finally:
        db.close()


@app.post('/api/orders/{token}/status', name='api_update_order_status')
async def api_update_order_status(token: str, request: Request):
    """Update an order's status via JSON or form data.

    JSON callers receive the updated order.
    Browser form submissions are redirected to the order detail page.
    """
    content_type = request.headers.get('content-type', '')
    is_json = 'application/json' in content_type

    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(token=token).first()
        if not order:
            if is_json:
                raise HTTPException(status_code=404, detail='not_found')
            return RedirectResponse(url='/', status_code=303)

        if is_json:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)

        new_status = (data.get('status') or '').strip()
        if not new_status:
            if is_json:
                raise HTTPException(status_code=400, detail='missing_status')
            return RedirectResponse(url=f'/os/{token}', status_code=303)

        order.status = new_status
        db.commit()
        db.refresh(order)

        if is_json:
            return _order_to_dict(order)
        _flash(request, 'Status atualizado.', 'success')
        return RedirectResponse(url=f'/os/{token}', status_code=303)
    finally:
        db.close()


@app.delete('/api/orders/{token}', name='api_delete_order')
def api_delete_order(token: str):
    """Delete an order by token."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(token=token).first()
        if not order:
            raise HTTPException(status_code=404, detail='not_found')
        db.delete(order)
        db.commit()
        return {'deleted': token}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------

@app.get('/qr/{token}.png', name='qr_code_image')
def qr_code_image(token: str):
    """Generate and return the QR code image for an order on-the-fly."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(token=token).first()
        if not order:
            raise HTTPException(status_code=404)
    finally:
        db.close()

    img_io = io.BytesIO()
    if qrcode:
        qr_img = qrcode.make(f"{FRONTEND_URL}/os/{token}")
        qr_img.save(img_io, format='PNG')
    img_io.seek(0)
    return Response(content=img_io.read(), media_type='image/png')


if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run('main:app', host='0.0.0.0', port=port, reload=True)

