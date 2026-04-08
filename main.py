"""
FastAPI application for managing Orders of Service (OS) — reads/writes Firebird (DADOS5.FDB).
"""

import csv
import io
import logging
import os
from math import ceil
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import create_engine, Column, Integer, String, Float, Date, ForeignKey, cast, text
from sqlalchemy import Date as SADate
from sqlalchemy.orm import sessionmaker, declarative_base

try:
    import qrcode
except ImportError:
    qrcode = None

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:8000').rstrip('/')

# ---------------------------------------------------------------------------
# Database setup — Firebird 2.5 (ODS 11.2)
# charset=WIN1252 is mandatory for Brazilian ERP databases (Delphi encoding).
# FIREBIRD_FILE must be the path inside the Docker container (e.g. /data/DADOS5.FDB).
# ---------------------------------------------------------------------------
fb_host     = os.environ.get('FIREBIRD_HOST', 'localhost')
fb_port     = os.environ.get('FIREBIRD_PORT', '3050')
fb_file     = os.environ['FIREBIRD_FILE']
fb_user     = os.environ.get('FIREBIRD_USER', 'SYSDBA')
fb_password = os.environ['FIREBIRD_PASSWORD']

_db_url = f"firebird+fdb://{fb_user}:{fb_password}@{fb_host}:{fb_port}/{fb_file}?charset=NONE"

engine       = create_engine(_db_url, pool_pre_ping=True)

# Firebird 2.5 does not support RETURNING clause — sqlalchemy-firebird 2.1
# leaves insert_returning=True at class level and only fixes it inside
# dialect.initialize(), which runs on first connect. Force it off early so
# the compiled INSERT never includes a RETURNING clause, which would cause
# a TypeError in SQLAlchemy's result-processing code.
engine.dialect.insert_returning = False
engine.dialect.update_returning = False
engine.dialect.delete_returning = False

SessionLocal = sessionmaker(bind=engine)
Base         = declarative_base()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class OrdemServico(Base):
    __tablename__ = 'ORDEMSERVICO'

    idordem          = Column(Integer, primary_key=True)
    empresa          = Column(Integer)
    nordem           = Column(String(20))
    datacadastro     = Column(Date)
    nprotocolo       = Column(String(50))
    idcliente        = Column(String(20))
    nomecliente      = Column(String(300))
    solicitante      = Column(String(100))
    fonesolicitante  = Column(String(15))
    descricao        = Column(String(200))
    nserie           = Column(String(30))
    marca            = Column(String(100))
    situacao         = Column(String(30))
    volts            = Column(String(10))
    idvendedor       = Column(Integer)
    vendedor         = Column(String(100))
    idtecnico        = Column(Integer)
    tecnico          = Column(String(100))
    datapentrega     = Column(Date)
    datapentregadias = Column(Integer)
    dataconclusao    = Column(Date)
    dataentrega      = Column(Date)
    horaini          = Column(String(10))
    horafin          = Column(String(10))
    horatotal        = Column(String(10))
    tipoatendimento  = Column(String(100))
    localatendimento = Column(String(100))
    defeito          = Column(String(3000))
    reparo           = Column(String(3000))
    anota            = Column(String(10000))
    garantiaanota    = Column(String(10000))
    garantia         = Column(String(10))
    garantiadata     = Column(Date)
    vlpecas          = Column(Float)
    vlservicos       = Column(Float)
    vldeslocamento   = Column(Float)
    kmtotal          = Column(Float)
    vldesconto       = Column(Float)
    vlacrescimo      = Column(Float)
    vltotal          = Column(Float)
    vlsaldo          = Column(Float)
    formadepagto     = Column(String(50))
    condpagtocod     = Column(String(2))
    condpagto        = Column(String(20))
    prioridade       = Column(String(20))
    dataalt          = Column(Date)
    usuarioalt       = Column(String(30))
    datacad          = Column(Date)
    usuariocad       = Column(String(30))
    osmail           = Column(String(300))
    dataaprovacao    = Column(Date)


class OsHist(Base):
    __tablename__ = 'OSHIST'

    idoshist = Column(Integer, primary_key=True)
    empresa  = Column(Integer)
    idordem  = Column(Integer, ForeignKey('ORDEMSERVICO.IDORDEM'))
    situacao = Column(String(30))
    data     = Column(Date)
    hora     = Column(String(10))
    usuario  = Column(String(30))


# ---------------------------------------------------------------------------
# Load COLOR_MAP from OSTIPO at startup
# ---------------------------------------------------------------------------

_DELPHI_TO_CSS = {
    'clGreen':  '#28a745',
    'clRed':    '#dc3545',
    'clGray':   '#6c757d',
    'clPurple': '#6f42c1',
    'clTeal':   '#20c997',
    'clBlue':   '#0d6efd',
}

def _decode(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode('win1252', errors='replace').strip()
    return v.strip() if isinstance(v, str) else v

def _load_color_map(db) -> dict:
    rows = db.execute(text("SELECT SITUACAO, COR FROM OSTIPO")).fetchall()
    return {_decode(r[0]): _DELPHI_TO_CSS.get(_decode(r[1]), '#6c757d') for r in rows}

_db = SessionLocal()
try:
    COLOR_MAP = _load_color_map(_db)
finally:
    _db.close()


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Inovatech OS")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get('SECRET_KEY', 'dev-only-insecure-key'),
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

PAGE_SIZE = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order_to_dict(order: OrdemServico) -> dict:
    return {
        'idordem':         order.idordem,
        'nordem':          order.nordem,
        'nomecliente':     order.nomecliente,
        'solicitante':     order.solicitante,
        'fonesolicitante': order.fonesolicitante,
        'descricao':       order.descricao,
        'defeito':         order.defeito,
        'reparo':          order.reparo,
        'situacao':        order.situacao,
        'tecnico':         order.tecnico,
        'marca':           order.marca,
        'nserie':          order.nserie,
        'vltotal':         order.vltotal,
        'datacadastro':    order.datacadastro.isoformat() if order.datacadastro else None,
        'datapentrega':    order.datapentrega.isoformat() if order.datapentrega else None,
        'prioridade':      order.prioridade,
    }


def _filtered_query(
    db,
    situacao: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    search: Optional[str] = None,
):
    q = db.query(OrdemServico)
    if situacao:
        q = q.filter(OrdemServico.situacao == situacao)
    if start:
        q = q.filter(cast(OrdemServico.datacadastro, SADate) >= start)
    if end:
        q = q.filter(cast(OrdemServico.datacadastro, SADate) <= end)
    if search:
        search_value = search.strip()
        if search_value:
            q = q.filter(
                text(
                    "("
                    "NORDEM CONTAINING :search "
                    "OR NOMECLIENTE CONTAINING :search "
                    "OR DESCRICAO CONTAINING :search"
                    ")"
                )
            )
            q = q.params(search=search_value)
    return q


def _coerce_page(page: int) -> int:
    return max(page, 1)


def _list_query_params(
    situacao: str = '',
    start: str = '',
    end: str = '',
    search: str = '',
    page: Optional[int] = None,
) -> dict:
    params = {}
    if situacao:
        params['situacao'] = situacao
    if start:
        params['start'] = start
    if end:
        params['end'] = end
    if search:
        params['search'] = search
    if page and page > 1:
        params['page'] = page
    return params


def _build_list_url(
    situacao: str = '',
    start: str = '',
    end: str = '',
    search: str = '',
    page: Optional[int] = None,
) -> str:
    params = _list_query_params(situacao, start, end, search, page)
    query = urlencode(params)
    return f'/?{query}' if query else '/'


def _build_pagination_items(current_page: int, total_pages: int) -> list[dict]:
    if total_pages <= 1:
        return []

    pages = {1, total_pages, current_page}
    for offset in range(1, 3):
        pages.add(current_page - offset)
        pages.add(current_page + offset)

    valid_pages = sorted(page for page in pages if 1 <= page <= total_pages)
    items = []
    previous_page = None
    for page in valid_pages:
        if previous_page is not None and page - previous_page > 1:
            items.append({'kind': 'ellipsis'})
        items.append({'kind': 'page', 'number': page, 'is_current': page == current_page})
        previous_page = page
    return items


def _build_index_context(
    request: Request,
    orders: list[OrdemServico],
    situacao: str,
    start: str,
    end: str,
    search: str,
    page: int,
    total_orders: int,
    total_pages: int,
) -> dict:
    offset = (page - 1) * PAGE_SIZE
    start_index = offset + 1 if total_orders else 0
    end_index = min(offset + PAGE_SIZE, total_orders)
    base_params = _list_query_params(situacao, start, end, search)

    return {
        'request': request,
        'orders': orders,
        'color_map': COLOR_MAP,
        'status_filter': situacao,
        'date_from': start,
        'date_to': end,
        'search_term': search,
        'export_url': f"/export?{urlencode(base_params)}" if base_params else '/export',
        'list_url': _build_list_url(situacao, start, end, search, page),
        'list_url_encoded': quote(_build_list_url(situacao, start, end, search, page), safe=''),
        'current_page': page,
        'total_pages': total_pages,
        'total_orders': total_orders,
        'page_size': PAGE_SIZE,
        'start_index': start_index,
        'end_index': end_index,
        'prev_page_url': _build_list_url(situacao, start, end, search, page - 1) if page > 1 else None,
        'next_page_url': _build_list_url(situacao, start, end, search, page + 1) if page < total_pages else None,
        'pagination_items': [
            {
                **item,
                'url': _build_list_url(situacao, start, end, search, item['number']),
            } if item['kind'] == 'page' else item
            for item in _build_pagination_items(page, total_pages)
        ],
    }


def _db_error_message(exc: Exception) -> str:
    """Extract a readable message from a SQLAlchemy/Firebird exception."""
    cause = getattr(exc, 'orig', None) or getattr(exc, '__cause__', None)
    msg = str(cause) if cause else str(exc)
    # Strip SQLAlchemy wrapper lines — keep only the first meaningful line
    first_line = msg.strip().splitlines()[0] if msg.strip() else msg
    return first_line or 'Erro desconhecido.'


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
def index(request: Request, situacao: str = '', start: str = '', end: str = '', search: str = '', page: int = 1):
    db = SessionLocal()
    try:
        q = _filtered_query(db, situacao or None, start or None, end or None, search or None)
        total_orders = q.count()
        total_pages = max(ceil(total_orders / PAGE_SIZE), 1)
        page = min(_coerce_page(page), total_pages)
        offset = (page - 1) * PAGE_SIZE
        orders = (
            q.order_by(OrdemServico.datacadastro.desc(), OrdemServico.idordem.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
            .all()
        )
        context = _build_index_context(
            request=request,
            orders=orders,
            situacao=situacao,
            start=start,
            end=end,
            search=search,
            page=page,
            total_orders=total_orders,
            total_pages=total_pages,
        )
        if request.headers.get('x-partial-render') == 'order-list':
            return templates.TemplateResponse(request, '_order_list_content.html', context)
        context['messages'] = _pop_flash(request)
        return templates.TemplateResponse(request, 'list_os.html', context)
    finally:
        db.close()


@app.get('/new', response_class=HTMLResponse, name='new_order')
def new_order(request: Request):
    return templates.TemplateResponse(request, 'new_os.html', {
        'statuses': list(COLOR_MAP.keys()),
        'messages': _pop_flash(request),
    })


@app.get('/os/{nordem}', response_class=HTMLResponse, name='order_detail')
def order_detail(nordem: str, request: Request, return_to: str = '/'):
    db = SessionLocal()
    try:
        order = db.query(OrdemServico).filter(OrdemServico.nordem == int(nordem)).first()
        if not order:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(request, 'os_detail.html', {
            'order': order,
            'color_map': COLOR_MAP,
            'statuses': list(COLOR_MAP.keys()),
            'return_to': return_to or '/',
            'messages': _pop_flash(request),
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get('/export', name='export_orders')
def export_orders(situacao: str = '', start: str = '', end: str = '', search: str = ''):
    db = SessionLocal()
    try:
        q = _filtered_query(db, situacao or None, start or None, end or None, search or None)
        orders = q.order_by(OrdemServico.datacadastro.desc()).all()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'nordem', 'nomecliente', 'solicitante', 'fonesolicitante',
            'descricao', 'defeito', 'reparo', 'situacao',
            'tecnico', 'marca', 'nserie', 'vltotal',
            'datacadastro', 'datapentrega', 'prioridade',
        ])
        for o in orders:
            writer.writerow([
                o.nordem, o.nomecliente, o.solicitante, o.fonesolicitante,
                o.descricao, o.defeito, o.reparo, o.situacao,
                o.tecnico, o.marca, o.nserie, o.vltotal,
                o.datacadastro.isoformat() if o.datacadastro else '',
                o.datapentrega.isoformat() if o.datapentrega else '',
                o.prioridade,
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
def api_list_orders(situacao: str = '', start: str = '', end: str = '', search: str = '', page: int = 1):
    db = SessionLocal()
    try:
        q = _filtered_query(db, situacao or None, start or None, end or None, search or None)
        total_orders = q.count()
        total_pages = max(ceil(total_orders / PAGE_SIZE), 1)
        page = min(_coerce_page(page), total_pages)
        offset = (page - 1) * PAGE_SIZE
        orders = (
            q.order_by(OrdemServico.datacadastro.desc(), OrdemServico.idordem.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
            .all()
        )
        return {
            'orders': [_order_to_dict(o) for o in orders],
            'pagination': {
                'page': page,
                'page_size': PAGE_SIZE,
                'total_orders': total_orders,
                'total_pages': total_pages,
                'has_previous': page > 1,
                'has_next': page < total_pages,
            },
        }
    finally:
        db.close()


@app.get('/api/orders/{nordem}', name='api_get_order')
def api_get_order(nordem: str):
    db = SessionLocal()
    try:
        order = db.query(OrdemServico).filter(OrdemServico.nordem == int(nordem)).first()
        if not order:
            raise HTTPException(status_code=404, detail='not_found')
        return _order_to_dict(order)
    finally:
        db.close()


@app.post('/api/orders', name='api_create_order')
async def api_create_order(request: Request):
    content_type = request.headers.get('content-type', '')
    is_json = 'application/json' in content_type

    if is_json:
        data = await request.json()
    else:
        form = await request.form()
        data = dict(form)

    nordem      = (data.get('nordem') or '').strip()
    nomecliente = (data.get('nomecliente') or '').strip()
    solicitante = (data.get('solicitante') or '').strip()
    descricao   = (data.get('descricao') or '').strip()
    defeito     = (data.get('defeito') or '').strip()
    situacao    = (data.get('situacao') or 'Em Andamento').strip() or 'Em Andamento'

    if not (nordem and nomecliente and descricao):
        if is_json:
            raise HTTPException(status_code=400, detail='missing_fields')
        _flash(request, 'N° OS, cliente e equipamento são obrigatórios.', 'danger')
        return templates.TemplateResponse(request, 'new_os.html', {
            'statuses': list(COLOR_MAP.keys()),
            'messages': _pop_flash(request),
        }, status_code=422)

    db = SessionLocal()
    try:
        next_id = db.execute(
            text("SELECT GEN_ID(GEN_ORDEMSERVICO_ID, 1) FROM RDB$DATABASE")
        ).scalar()
        order = OrdemServico(
            idordem      = next_id,
            nordem       = nordem,
            nomecliente  = nomecliente,
            solicitante  = solicitante,
            fonesolicitante = (data.get('fonesolicitante') or '').strip(),
            descricao    = descricao,
            defeito      = defeito,
            situacao     = situacao,
            datacadastro = date.today(),
            datacad      = date.today(),
            usuariocad   = 'sistema',
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        if is_json:
            return JSONResponse(_order_to_dict(order), status_code=201)
        _flash(request, 'Ordem criada com sucesso!', 'success')
        return RedirectResponse(url='/', status_code=303)
    except Exception as exc:
        db.rollback()
        logging.exception("Erro ao criar ordem de serviço")
        error_msg = _db_error_message(exc)
        if is_json:
            raise HTTPException(status_code=500, detail=error_msg)
        _flash(request, f'Erro ao salvar: {error_msg}', 'danger')
        return templates.TemplateResponse(request, 'new_os.html', {
            'statuses': list(COLOR_MAP.keys()),
            'messages': _pop_flash(request),
            'form_data': data,
        }, status_code=422)
    finally:
        db.close()


@app.post('/api/orders/{nordem}/status', name='api_update_order_status')
async def api_update_order_status(nordem: str, request: Request):
    content_type = request.headers.get('content-type', '')
    is_json = 'application/json' in content_type

    db = SessionLocal()
    try:
        order = db.query(OrdemServico).filter(OrdemServico.nordem == int(nordem)).first()
        if not order:
            if is_json:
                raise HTTPException(status_code=404, detail='not_found')
            return RedirectResponse(url='/', status_code=303)

        if is_json:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)

        return_to = (data.get('return_to') or '/').strip() or '/'

        new_situacao = (data.get('situacao') or data.get('status') or '').strip()
        if not new_situacao:
            if is_json:
                raise HTTPException(status_code=400, detail='missing_situacao')
            return RedirectResponse(url=f'/os/{nordem}?return_to={quote(return_to, safe="/?=&")}', status_code=303)

        order.situacao = new_situacao
        hist = OsHist(
            idordem  = order.idordem,
            empresa  = order.empresa,
            situacao = new_situacao,
            data     = date.today(),
            hora     = datetime.now().strftime('%H:%M'),
            usuario  = data.get('usuario') or 'sistema',
        )
        db.add(hist)
        db.commit()

        if is_json:
            return JSONResponse({'ok': True, 'situacao': new_situacao})
        _flash(request, 'Status atualizado.', 'success')
        return RedirectResponse(url=f'/os/{nordem}?return_to={quote(return_to, safe="/?=&")}', status_code=303)
    finally:
        db.close()


@app.delete('/api/orders/{nordem}', name='api_delete_order')
def api_delete_order(nordem: str):
    db = SessionLocal()
    try:
        order = db.query(OrdemServico).filter(OrdemServico.nordem == int(nordem)).first()
        if not order:
            raise HTTPException(status_code=404, detail='not_found')
        db.delete(order)
        db.commit()
        return JSONResponse({'ok': True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------

@app.get('/qr/{nordem}.png', name='qr_code_image')
def qr_code_image(nordem: str):
    db = SessionLocal()
    try:
        order = db.query(OrdemServico).filter(OrdemServico.nordem == int(nordem)).first()
        if not order:
            raise HTTPException(status_code=404)
    finally:
        db.close()

    img_io = io.BytesIO()
    if qrcode:
        qr_img = qrcode.make(f"{FRONTEND_URL}/os/{nordem}")
        qr_img.save(img_io, format='PNG')
    img_io.seek(0)
    return Response(content=img_io.read(), media_type='image/png')


if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run('main:app', host='0.0.0.0', port=port, reload=True)
