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

import os
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash
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


@app.before_first_request
def create_db():
    """Create database tables and output directories if they don't exist."""
    db.create_all()
    os.makedirs(os.path.join(app.root_path, 'static', 'qrcodes'), exist_ok=True)


@app.route('/')
def index():
    """Display a list of all orders."""
    orders = Order.query.order_by(Order.data_entrada.desc()).all()
    return render_template('list_os.html', orders=orders)


@app.route('/new', methods=['GET', 'POST'])
def new_order():
    """Create a new order from a form.  On POST, save it and generate QR."""
    if request.method == 'POST':
        # Extract form fields
        cliente = request.form.get('cliente', '').strip()
        contato = request.form.get('contato', '').strip()
        produto = request.form.get('produto', '').strip()
        problema = request.form.get('problema', '').strip()
        status = request.form.get('status', 'Recebido')

        if not (cliente and contato and produto and problema):
            flash('Todos os campos são obrigatórios.', 'danger')
            return render_template('new_os.html')

        # Generate a unique token
        token = uuid.uuid4().hex
        # Create order entry
        order = Order(token=token, cliente=cliente, contato=contato,
                      produto=produto, problema=problema, status=status)
        db.session.add(order)
        db.session.commit()

        # Build URL for this order's detail page
        order_url = url_for('order_detail', token=token, _external=True)

        # Generate QR code if qrcode library is available
        if qrcode:
            qr_img = qrcode.make(order_url)
            qr_path = os.path.join(app.root_path, order.qr_code_filename())
            qr_img.save(qr_path)
        else:
            # If qrcode is not available, leave a placeholder file
            qr_path = os.path.join(app.root_path, order.qr_code_filename())
            with open(qr_path, 'wb') as f:
                pass  # Create empty file as placeholder

        flash('Ordem criada com sucesso! Etiqueta com QR gerada.', 'success')
        return redirect(url_for('index'))

    return render_template('new_os.html')


@app.route('/os/<token>')
def order_detail(token: str):
    """Show the details of a single order using its unique token."""
    order = Order.query.filter_by(token=token).first_or_404()
    return render_template('os_detail.html', order=order)


@app.route('/os/<token>/update', methods=['POST'])
def update_order(token: str):
    """Update the status of an order from the dashboard."""
    order = Order.query.filter_by(token=token).first_or_404()
    new_status = request.form.get('status')
    if new_status:
        order.status = new_status
        db.session.commit()
        flash('Status atualizado.', 'success')
    return redirect(url_for('order_detail', token=token))


if __name__ == '__main__':
    app.run(debug=True)