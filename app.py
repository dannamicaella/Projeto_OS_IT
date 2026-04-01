"""
Simple Flask application for managing Orders of Service (OS) with QR Codes.

This application allows an administrator to create new orders, automatically
generates a unique token for each order and a corresponding QR Code pointing
to the order details.  A small label containing only the QR Code can be
printed and attached to the product (e.g. a laptop).  Technicians can
scan the code to view the full order details via a dashboard.

To run this app you need to install Flask, SQLAlchemy and qrcode:

    pip install Flask SQLAlchemy qrcode pillow

Then initialize the database by running this file once.  A SQLite
database will be created in the current directory.
"""

import csv
import io
import os
import uuid
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5000').rstrip('/')

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy

try:
    import qrcode
except ImportError:
    qrcode = None


app = Flask(__name__)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///os.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'inovatech-secret-key'

db = SQLAlchemy(app)


class Order(db.Model):
    """Represents an order of service entry."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    cliente = db.Column(db.String(120), nullable=False)
    contato = db.Column(db.String(120), nullable=False)
    produto = db.Column(db.String(120), nullable=False)
    problema = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Recebido', nullable=False)
    data_entrada = db.Column(db.DateTime, default=datetime.utcnow)

    def qr_code_filename(self) -> str:
        """Return the filename for the QR image for this order."""
        return f"static/qrcodes/{self.token}.png"

    def qr_code_url(self) -> str:
        """Return the URL for the QR code image (relative to static)."""
        return f"/static/qrcodes/{self.token}.png"


def create_db():
    """Create database tables and output directories if they don't exist."""
    db.create_all()
    os.makedirs(os.path.join(app.root_path, 'static', 'qrcodes'), exist_ok=True)


COLOR_MAP = {
    'Recebido': '#28a745',
    'Em análise': '#ffc107',
    'Aguardando aprovação': '#fd7e14',
    'Em execução': '#d63384',
    'Pronto': '#0d6efd',
}


def _order_to_dict(order):
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


def _persist_order(cliente, contato, produto, problema, status='Recebido'):
    """Create an order, commit it, and generate its QR code. Returns the Order."""
    token = uuid.uuid4().hex
    order = Order(token=token, cliente=cliente, contato=contato,
                  produto=produto, problema=problema, status=status)
    db.session.add(order)
    db.session.commit()
    qr_path = os.path.join(app.root_path, order.qr_code_filename())
    if qrcode:
        qr_img = qrcode.make(f"{FRONTEND_URL}/os/{token}")
        qr_img.save(qr_path)
    else:
        open(qr_path, 'wb').close()
    return order


def _filtered_query():
    """Return an Order query filtered by the current request's query params."""
    status_filter = request.args.get('status', '').strip() or None
    date_from = request.args.get('start', '').strip() or None
    date_to = request.args.get('end', '').strip() or None
    q = Order.query
    if status_filter:
        q = q.filter(Order.status == status_filter)
    if date_from:
        q = q.filter(db.func.date(Order.data_entrada) >= date_from)
    if date_to:
        q = q.filter(db.func.date(Order.data_entrada) <= date_to)
    return q, status_filter, date_from, date_to


@app.route('/')
def index():
    """Display a list of all orders with optional status/date filters."""
    q, status_filter, date_from, date_to = _filtered_query()
    orders = q.order_by(Order.data_entrada.desc()).all()
    return render_template(
        'list_os.html',
        orders=orders,
        color_map=COLOR_MAP,
        status_filter=status_filter or '',
        date_from=date_from or '',
        date_to=date_to or '',
    )


@app.route('/export')
def export_orders():
    """Export orders as CSV, respecting the same filters as the list view."""
    q, _, _, _ = _filtered_query()
    orders = q.order_by(Order.data_entrada.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'token', 'cliente', 'contato', 'produto', 'problema', 'status', 'data_entrada'])
    for o in orders:
        writer.writerow([o.id, o.token, o.cliente, o.contato, o.produto, o.problema, o.status, o.data_entrada.isoformat()])
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=ordens_servico.csv'},
    )


@app.route('/api/orders', methods=['GET'])
def api_list_orders():
    """Return all orders (with optional filters) as JSON."""
    q, _, _, _ = _filtered_query()
    orders = q.order_by(Order.data_entrada.desc()).all()
    return jsonify({'orders': [_order_to_dict(o) for o in orders]})


@app.route('/api/orders/<token>', methods=['GET'])
def api_get_order(token: str):
    """Return a single order by token as JSON."""
    order = Order.query.filter_by(token=token).first()
    if not order:
        return jsonify({'error': 'not_found'}), 404
    return jsonify(_order_to_dict(order))


@app.route('/api/orders', methods=['POST'])
def api_create_order():
    """Create a new order via JSON or form data.

    JSON callers receive a 201 response with the created order.
    Browser form submissions are redirected to the index page.
    """
    data = request.get_json(silent=True) or {}
    cliente = (data.get('cliente') or request.form.get('cliente', '')).strip()
    contato = (data.get('contato') or request.form.get('contato', '')).strip()
    produto = (data.get('produto') or request.form.get('produto', '')).strip()
    problema = (data.get('problema') or request.form.get('problema', '')).strip()
    status = (data.get('status') or request.form.get('status', 'Recebido')).strip() or 'Recebido'
    if not (cliente and contato and produto and problema):
        if request.is_json:
            return jsonify({'error': 'missing_fields'}), 400
        flash('Todos os campos são obrigatórios.', 'danger')
        return render_template('new_os.html', statuses=list(COLOR_MAP.keys()))
    order = _persist_order(cliente, contato, produto, problema, status)
    if request.is_json:
        return jsonify(_order_to_dict(order)), 201
    flash('Ordem criada com sucesso! Etiqueta com QR gerada.', 'success')
    return redirect(url_for('index'))


@app.route('/api/orders/<token>/status', methods=['POST'])
def api_update_order_status(token: str):
    """Update an order's status via JSON or form data.

    JSON callers receive the updated order.
    Browser form submissions are redirected to the order detail page.
    """
    order = Order.query.filter_by(token=token).first()
    if not order:
        if request.is_json:
            return jsonify({'error': 'not_found'}), 404
        return redirect(url_for('index'))
    data = request.get_json(silent=True) or {}
    new_status = (data.get('status') or request.form.get('status', '')).strip()
    if not new_status:
        if request.is_json:
            return jsonify({'error': 'missing_status'}), 400
        return redirect(url_for('order_detail', token=token))
    order.status = new_status
    db.session.commit()
    if request.is_json:
        return jsonify(_order_to_dict(order))
    flash('Status atualizado.', 'success')
    return redirect(url_for('order_detail', token=token))


@app.route('/new')
def new_order():
    """Render the new order form."""
    return render_template('new_os.html', statuses=list(COLOR_MAP.keys()))


@app.route('/os/<token>')
def order_detail(token: str):
    """Show the details of a single order using its unique token."""
    order = Order.query.filter_by(token=token).first_or_404()
    return render_template('os_detail.html', order=order, statuses=list(COLOR_MAP.keys()))


if __name__ == '__main__':
    with app.app_context():
        create_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, port=port)