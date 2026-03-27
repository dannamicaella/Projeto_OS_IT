"""
Standalone HTTP server to manage Orders of Service (OS) with QR Codes using
only Python's standard library.  This avoids external dependencies such as
Flask or SQLAlchemy, making it possible to run in restricted environments.

Features:
  * List all orders of service
  * Create a new order via an HTML form
  * Generate a unique token for each order and display a QR Code (via
    Google Chart API) that links back to the order details
  * View order details and update its status

Usage:
  1. Run this script: ``python server.py``
  2. Open a browser at http://localhost:8000/ to access the dashboard

This script uses SQLite (built-in) for persistent storage.  The database
file ``os.db`` will be created in the same directory if it does not exist.
"""

import os
import sqlite3
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, quote, unquote
import json
import socket


DB_FILE = os.path.join(os.path.dirname(__file__), 'os.db')


def init_db() -> None:
    """Initialize the SQLite database with the required table."""
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                cliente TEXT NOT NULL,
                contato TEXT NOT NULL,
                produto TEXT NOT NULL,
                problema TEXT NOT NULL,
                status TEXT NOT NULL,
                data_entrada TEXT NOT NULL
            )
            """
        )
        conn.commit()


def fetch_orders(status: str | None = None,
                 date_from: str | None = None,
                 date_to: str | None = None) -> list:
    """
    Return orders sorted by date descending.  Optionally filter by status
    and by a date range.  Dates must be strings in ``YYYY-MM-DD`` format.

    Filtering is done at the database level using SQLite's ``date``
    function on the ISO timestamp stored in ``data_entrada``.

    :param status: optional status string to filter by (e.g. 'Recebido').
    :param date_from: optional start date (inclusive) ``YYYY-MM-DD``.
    :param date_to: optional end date (inclusive) ``YYYY-MM-DD``.
    :return: list of tuple rows.
    """
    query = "SELECT id, token, cliente, contato, produto, problema, status, data_entrada FROM orders WHERE 1=1"
    params: list = []
    if status:
        query += " AND status=?"
        params.append(status)
    if date_from:
        query += " AND date(data_entrada) >= date(?)"
        params.append(date_from)
    if date_to:
        query += " AND date(data_entrada) <= date(?)"
        params.append(date_to)
    query += " ORDER BY datetime(data_entrada) DESC"
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
    return rows


def fetch_order_by_token(token: str):
    """Return a single order by its token or None if not found."""
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, token, cliente, contato, produto, problema, status, data_entrada FROM orders WHERE token=?", (token,))
        row = cur.fetchone()
    return row


def insert_order(cliente: str, contato: str, produto: str, problema: str, status: str = 'Recebido') -> str:
    """Insert a new order into the database and return its token."""
    token = uuid.uuid4().hex
    data_entrada = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders (token, cliente, contato, produto, problema, status, data_entrada) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, cliente, contato, produto, problema, status, data_entrada),
        )
        conn.commit()
    return token


def update_order_status(token: str, new_status: str) -> bool:
    """Update the status of an order.  Returns True if updated, False otherwise."""
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status=? WHERE token=?", (new_status, token))
        conn.commit()
        return cur.rowcount > 0


class OSHandler(BaseHTTPRequestHandler):
    """HTTP request handler to serve the OS dashboard and forms."""

    def _render_template(self, title: str, content: str) -> bytes:
        """Wrap content in a basic HTML page with Bootstrap."""
        page = f"""<!doctype html>
<html lang='pt-br'>
<head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>{title}</title>
    <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css' rel='stylesheet'>
</head>
<body class='bg-light'>
    <nav class='navbar navbar-expand-lg navbar-dark bg-primary mb-4'>
        <div class='container'>
            <a class='navbar-brand' href='/'>Inovatech OS</a>
            <div class='collapse navbar-collapse'>
                <ul class='navbar-nav ms-auto'>
                    <li class='nav-item'><a class='nav-link' href='/new'>Nova Ordem</a></li>
                </ul>
            </div>
        </div>
    </nav>
    <div class='container'>
        {content}
    </div>
    <script src='https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'></script>
</body>
</html>"""
        return page.encode('utf-8')

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        # API endpoints take precedence
        if path.startswith('/api/'):
            self._handle_api_get(parsed)
            return
        # Static file serving for front-end assets
        if path == '/index.html' or path == '/':
            # If a static index.html exists, serve it; otherwise fallback to server-rendered list
            static_path = os.path.join(os.path.dirname(__file__), 'static', 'index.html')
            if os.path.exists(static_path):
                self._serve_file(static_path, content_type='text/html')
                return
            # fallback to dashboard
            self._handle_list_orders()
            return
        if path == '/new':
            self._handle_new_order_form()
            return
        if path.startswith('/export'):
            self._handle_export_orders()
            return
        if path.startswith('/os/'):
            segments = path.strip('/').split('/')
            if len(segments) >= 2:
                token = segments[1]
                self._handle_order_detail(token)
                return
            self.send_error(404)
            return
        # Serve files from the static directory if requested
        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        file_path = os.path.join(static_dir, path.lstrip('/'))
        if os.path.commonprefix([os.path.abspath(file_path), os.path.abspath(static_dir)]) == os.path.abspath(static_dir) and os.path.exists(file_path):
            # Determine content type by extension
            ext = os.path.splitext(file_path)[1].lower()
            content_type = 'text/plain'
            if ext == '.js':
                content_type = 'application/javascript'
            elif ext == '.css':
                content_type = 'text/css'
            elif ext == '.html':
                content_type = 'text/html'
            elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.svg'):
                # We'll send binary for images
                self._serve_file(file_path, binary=True)
                return
            self._serve_file(file_path, content_type=content_type)
            return
        # fallback
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8')
        form = parse_qs(body)
        # API endpoints
        if path.startswith('/api/'):
            self._handle_api_post(parsed, form)
            return
        if path == '/new':
            self._handle_new_order_submission(form)
            return
        if path.startswith('/os/') and path.endswith('/update'):
            segments = path.strip('/').split('/')
            if len(segments) >= 3:
                token = segments[1]
                self._handle_order_update(token, form)
                return
            self.send_error(404)
            return
        # fallback
        self.send_error(404)

    # Helper methods for routes

    def _handle_list_orders(self):
        """
        Render the list of orders.  Supports optional filtering by status via
        the ``status`` query parameter.  A small form with a dropdown is
        displayed above the table to allow the user to select a status and
        filter the results.  If no filter is applied, all orders are shown.
        """
        # Parse query parameters for status and date filters
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        status_filter: str | None = None
        date_from: str | None = None
        date_to: str | None = None
        # Extract status value
        if 'status' in params:
            raw = params['status'][0]
            status_filter = raw.strip() or None
        # Extract date range values; expect YYYY-MM-DD
        if 'start' in params:
            raw_from = params['start'][0].strip()
            date_from = raw_from if raw_from else None
        if 'end' in params:
            raw_to = params['end'][0].strip()
            date_to = raw_to if raw_to else None

        # Fetch orders with optional filters
        orders = fetch_orders(status_filter, date_from, date_to)

        # Define colour map for statuses for table display and legend
        color_map = {
            'Recebido': '#28a745',  # green
            'Em análise': '#ffc107',  # yellow
            'Aguardando aprovação': '#fd7e14',  # orange
            'Em execução': '#d63384',  # pink
            'Pronto': '#0d6efd',  # blue
        }

        # Build HTML rows
        rows_html = []
        for (id_, token, cliente, contato, produto, problema, status, data_entrada) in orders:
            date_obj = datetime.fromisoformat(data_entrada)
            date_str = date_obj.strftime('%d/%m/%Y %H:%M')
            detail_url = f"/os/{token}"
            qr_url = self._qr_url(detail_url)
            color = color_map.get(status, '#000')
            # status cell colored text
            status_html = f"<span style='color:{color}; font-weight:600;'>{status}</span>"
            rows_html.append(
                f"<tr>"
                f"<td>{id_}</td>"
                f"<td>{cliente}</td>"
                f"<td>{produto}</td>"
                f"<td>{status_html}</td>"
                f"<td>{date_str}</td>"
                f"<td><a href='{detail_url}'><img src='{qr_url}' alt='QR' style='width:40px;height:40px'></a></td>"
                f"<td><a class='btn btn-sm btn-secondary' href='{detail_url}'>Detalhes</a></td>"
                f"</tr>"
            )
        table_rows = "\n".join(rows_html) if rows_html else "<tr><td colspan='7' class='text-center'>Nenhuma ordem cadastrada.</td></tr>"

        # Build legend for colour mapping
        legend_items = []
        for label, color in color_map.items():
            legend_items.append(
                f"<span class='d-inline-flex align-items-center me-3'><span style='width:12px;height:12px;border-radius:50%;background:{color};display:inline-block;margin-right:4px;'></span>{label}</span>"
            )
        legend_html = "".join(legend_items)

        # Build filter form (status + date range)
        status_options = ['Recebido', 'Em análise', 'Aguardando aprovação', 'Em execução', 'Pronto']
        # Status select options
        status_select_html = "<option value=''>Todos</option>"
        for opt in status_options:
            selected = "selected" if status_filter == opt else ""
            status_select_html += f"<option value='{opt}' {selected}>{opt}</option>"
        # Preserve date filter values in input fields
        start_value = date_from or ''
        end_value = date_to or ''
        filter_form = f"""
<form method='get' class='mb-3 row g-2'>
    <div class='col-auto'>
        <label for='statusFilter' class='col-form-label'>Status:</label>
    </div>
    <div class='col-auto'>
        <select class='form-select' id='statusFilter' name='status'>
            {status_select_html}
        </select>
    </div>
    <div class='col-auto'>
        <label for='startDate' class='col-form-label'>Data inicial:</label>
    </div>
    <div class='col-auto'>
        <input type='date' class='form-control' id='startDate' name='start' value='{start_value}'>
    </div>
    <div class='col-auto'>
        <label for='endDate' class='col-form-label'>Data final:</label>
    </div>
    <div class='col-auto'>
        <input type='date' class='form-control' id='endDate' name='end' value='{end_value}'>
    </div>
    <div class='col-auto'>
        <button type='submit' class='btn btn-primary'>Aplicar</button>
    </div>
</form>
"""

        # Build export URL, preserving filters
        export_params = []
        if status_filter:
            export_params.append(f"status={quote(status_filter)}")
        if date_from:
            export_params.append(f"start={quote(date_from)}")
        if date_to:
            export_params.append(f"end={quote(date_to)}")
        export_query = '&'.join(export_params)
        export_href = f"/export?{export_query}" if export_query else "/export"

        content = f"""
<h1>Ordens de Serviço</h1>
{filter_form}
<table class='table table-striped table-bordered'>
    <thead class='table-light'>
        <tr>
            <th>ID</th><th>Cliente</th><th>Produto</th><th>Status</th><th>Entrada</th><th>QR Code</th><th>Ações</th>
        </tr>
    </thead>
    <tbody>
        {table_rows}
    </tbody>
</table>
<div class='mb-3 d-flex gap-2'>
    <a class='btn btn-primary' href='/new'>Nova Ordem</a>
    <a class='btn btn-outline-secondary' href='{export_href}'>Exportar CSV</a>
</div>
<div class='mt-4 pt-3 border-top'>
    <h6>Guia de cores</h6>
    {legend_html}
</div>
"""
        data = self._render_template('Ordens de Serviço', content)
        self._send_html(data)

    def _handle_new_order_form(self):
        form_html = """
<h1>Criar nova Ordem de Serviço</h1>
<form method='post' action='/new'>
    <div class='mb-3'>
        <label for='cliente' class='form-label'>Nome do cliente</label>
        <input type='text' class='form-control' id='cliente' name='cliente' required>
    </div>
    <div class='mb-3'>
        <label for='contato' class='form-label'>Contato (telefone ou e-mail)</label>
        <input type='text' class='form-control' id='contato' name='contato' required>
    </div>
    <div class='mb-3'>
        <label for='produto' class='form-label'>Produto/Equipamento</label>
        <input type='text' class='form-control' id='produto' name='produto' required>
    </div>
    <div class='mb-3'>
        <label for='problema' class='form-label'>Descrição do problema</label>
        <textarea class='form-control' id='problema' name='problema' rows='3' required></textarea>
    </div>
    <div class='mb-3'>
        <label for='status' class='form-label'>Status inicial</label>
        <select class='form-select' id='status' name='status'>
            <option value='Recebido'>Recebido</option>
            <option value='Em análise'>Em análise</option>
            <option value='Aguardando aprovação'>Aguardando aprovação</option>
            <option value='Em execução'>Em execução</option>
            <option value='Pronto'>Pronto</option>
        </select>
    </div>
    <button type='submit' class='btn btn-primary'>Salvar</button>
</form>
"""
        data = self._render_template('Nova Ordem', form_html)
        self._send_html(data)

    def _handle_new_order_submission(self, form: dict):
        # Extract data from form
        cliente = form.get('cliente', [''])[0].strip()
        contato = form.get('contato', [''])[0].strip()
        produto = form.get('produto', [''])[0].strip()
        problema = form.get('problema', [''])[0].strip()
        status = form.get('status', ['Recebido'])[0].strip()
        if not (cliente and contato and produto and problema):
            # Bad request, re-render form with message
            content = "<div class='alert alert-danger'>Todos os campos são obrigatórios.</div>"
            content += self._form_html_populated(cliente, contato, produto, problema, status)
            data = self._render_template('Nova Ordem', content)
            self._send_html(data)
            return
        # Insert order and redirect
        token = insert_order(cliente, contato, produto, problema, status)
        self.send_response(303)
        self.send_header('Location', '/')
        self.end_headers()

    def _form_html_populated(self, cliente, contato, produto, problema, status):
        """Return HTML form with previously entered values (used on error)."""
        # Reuse the same options list; mark selected
        status_options = ['Recebido', 'Em análise', 'Aguardando aprovação', 'Em execução', 'Pronto']
        options_html = "".join([
            f"<option value='{opt}' {'selected' if opt == status else ''}>{opt}</option>"
            for opt in status_options
        ])
        html = f"""
<h1>Criar nova Ordem de Serviço</h1>
<form method='post' action='/new'>
    <div class='mb-3'>
        <label for='cliente' class='form-label'>Nome do cliente</label>
        <input type='text' class='form-control' id='cliente' name='cliente' value='{cliente}' required>
    </div>
    <div class='mb-3'>
        <label for='contato' class='form-label'>Contato (telefone ou e-mail)</label>
        <input type='text' class='form-control' id='contato' name='contato' value='{contato}' required>
    </div>
    <div class='mb-3'>
        <label for='produto' class='form-label'>Produto/Equipamento</label>
        <input type='text' class='form-control' id='produto' name='produto' value='{produto}' required>
    </div>
    <div class='mb-3'>
        <label for='problema' class='form-label'>Descrição do problema</label>
        <textarea class='form-control' id='problema' name='problema' rows='3' required>{problema}</textarea>
    </div>
    <div class='mb-3'>
        <label for='status' class='form-label'>Status inicial</label>
        <select class='form-select' id='status' name='status'>{options_html}</select>
    </div>
    <button type='submit' class='btn btn-primary'>Salvar</button>
</form>
"""
        return html

    def _handle_order_detail(self, token: str):
        order = fetch_order_by_token(token)
        if not order:
            self.send_error(404, 'Ordem não encontrada')
            return
        id_, token, cliente, contato, produto, problema, status, data_entrada = order
        date_obj = datetime.fromisoformat(data_entrada)
        date_str = date_obj.strftime('%d/%m/%Y %H:%M')
        detail_url = f"/os/{token}"
        qr_url = self._qr_url(detail_url)
        # Build status options HTML
        status_options = ['Recebido', 'Em análise', 'Aguardando aprovação', 'Em execução', 'Pronto']
        options_html = "".join([
            f"<option value='{opt}' {'selected' if opt == status else ''}>{opt}</option>"
            for opt in status_options
        ])
        # Build the content with a download button for the QR code.  The
        # colour legend is shown on the dashboard only.
        content = f"""
<h1>Ordem #{id_}</h1>
<div class='row'>
    <div class='col-md-8'>
        <dl class='row'>
            <dt class='col-sm-3'>Cliente</dt><dd class='col-sm-9'>{cliente}</dd>
            <dt class='col-sm-3'>Contato</dt><dd class='col-sm-9'>{contato}</dd>
            <dt class='col-sm-3'>Produto</dt><dd class='col-sm-9'>{produto}</dd>
            <dt class='col-sm-3'>Problema</dt><dd class='col-sm-9'>{problema}</dd>
            <dt class='col-sm-3'>Status</dt>
            <dd class='col-sm-9'>
                <form method='post' action='/os/{token}/update' class='d-flex align-items-center'>
                    <select name='status' class='form-select form-select-sm me-2' style='max-width:200px;'>
                        {options_html}
                    </select>
                    <button type='submit' class='btn btn-sm btn-primary'>Atualizar</button>
                </form>
            </dd>
            <dt class='col-sm-3'>Data de Entrada</dt><dd class='col-sm-9'>{date_str}</dd>
        </dl>
    </div>
    <div class='col-md-4 text-center'>
        <h5>Etiqueta QR Code</h5>
        <img src='{qr_url}' alt='QR Code' class='img-fluid mb-2' style='max-width:180px;'>
        <a href='{qr_url}' download='OS_{id_}_qrcode.png' class='btn btn-sm btn-outline-primary'>Download</a>
    </div>
</div>
<a class='btn btn-secondary mt-3' href='/'>Voltar</a>
"""
        data = self._render_template(f"Ordem {id_}", content)
        self._send_html(data)

    # ==== Static file serving ==== #
    def _serve_file(self, filepath: str, content_type: str = None, binary: bool = False):
        """
        Serve a file from disk. If ``binary`` is True, open in binary mode and attempt to
        infer the content type from the extension. Otherwise open as text. A
        missing content_type will default to 'application/octet-stream' or a
        guess for images.
        """
        try:
            if binary:
                with open(filepath, 'rb') as f:
                    data = f.read()
                if content_type is None:
                    # Try to determine simple image types
                    ext = os.path.splitext(filepath)[1].lower()
                    if ext in ('.png', '.gif', '.jpg', '.jpeg'):
                        content_type = f'image/{ext.lstrip(".")}'
                    elif ext == '.svg':
                        content_type = 'image/svg+xml'
                    else:
                        content_type = 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = f.read().encode('utf-8')
                if content_type is None:
                    content_type = 'text/plain; charset=utf-8'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)

    # ==== JSON sending helper ====
    def _send_json(self, data, status_code: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2)
        body_bytes = body.encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    # ==== API handlers ====
    def _handle_api_get(self, parsed):
        path = parsed.path
        segments = path.strip('/').split('/')
        # /api/orders
        if len(segments) == 2 and segments[1] == 'orders':
            # list orders
            params = parse_qs(parsed.query)
            status_filter = params.get('status', [None])[0] or None
            date_from = params.get('start', [None])[0] or None
            date_to = params.get('end', [None])[0] or None
            rows = fetch_orders(status_filter, date_from, date_to)
            # Convert to list of dicts
            orders_list = []
            for (id_, token, cliente, contato, produto, problema, status, data_entrada) in rows:
                orders_list.append({
                    'id': id_,
                    'token': token,
                    'cliente': cliente,
                    'contato': contato,
                    'produto': produto,
                    'problema': problema,
                    'status': status,
                    'data_entrada': data_entrada,
                })
            self._send_json({'orders': orders_list})
            return
        # /api/orders/<token>
        if len(segments) == 3 and segments[1] == 'orders':
            token = segments[2]
            row = fetch_order_by_token(token)
            if not row:
                self._send_json({'error': 'not_found'}, status_code=404)
                return
            id_, token, cliente, contato, produto, problema, status, data_entrada = row
            order = {
                'id': id_,
                'token': token,
                'cliente': cliente,
                'contato': contato,
                'produto': produto,
                'problema': problema,
                'status': status,
                'data_entrada': data_entrada,
            }
            self._send_json(order)
            return
        # Unknown API GET endpoint
        self._send_json({'error': 'invalid_endpoint'}, status_code=404)

    def _handle_api_post(self, parsed, form: dict):
        path = parsed.path
        segments = path.strip('/').split('/')
        # Create new order: POST /api/orders
        if len(segments) == 2 and segments[1] == 'orders':
            # Accept x-www-form-urlencoded or JSON in body
            # If Content-Type is JSON, parse JSON
            content_type = self.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body) if body else {}
                cliente = data.get('cliente', '').strip()
                contato = data.get('contato', '').strip()
                produto = data.get('produto', '').strip()
                problema = data.get('problema', '').strip()
                status = data.get('status', 'Recebido').strip()
            else:
                cliente = form.get('cliente', [''])[0].strip()
                contato = form.get('contato', [''])[0].strip()
                produto = form.get('produto', [''])[0].strip()
                problema = form.get('problema', [''])[0].strip()
                status = form.get('status', ['Recebido'])[0].strip() or 'Recebido'
            if not (cliente and contato and produto and problema):
                self._send_json({'error': 'missing_fields'}, status_code=400)
                return
            token = insert_order(cliente, contato, produto, problema, status)
            # Return the created order details
            row = fetch_order_by_token(token)
            id_, token, cliente, contato, produto, problema, status, data_entrada = row
            order = {
                'id': id_,
                'token': token,
                'cliente': cliente,
                'contato': contato,
                'produto': produto,
                'problema': problema,
                'status': status,
                'data_entrada': data_entrada,
            }
            self._send_json(order, status_code=201)
            return
        # Update order status: POST /api/orders/<token>/status
        if len(segments) == 4 and segments[1] == 'orders' and segments[3] == 'status':
            token = segments[2]
            new_status = form.get('status', [''])[0].strip()
            if not new_status:
                self._send_json({'error': 'missing_status'}, status_code=400)
                return
            updated = update_order_status(token, new_status)
            if not updated:
                self._send_json({'error': 'not_found'}, status_code=404)
                return
            row = fetch_order_by_token(token)
            id_, token, cliente, contato, produto, problema, status, data_entrada = row
            order = {
                'id': id_,
                'token': token,
                'cliente': cliente,
                'contato': contato,
                'produto': produto,
                'problema': problema,
                'status': status,
                'data_entrada': data_entrada,
            }
            self._send_json(order)
            return
        # Unknown endpoint
        self._send_json({'error': 'invalid_endpoint'}, status_code=404)

    def _handle_export_orders(self):
        """
        Serve a CSV file containing all orders or those matching the current
        filters.  Supports the same query parameters as the dashboard
        (``status``, ``start`` and ``end``) to export only a subset of
        records.  The CSV contains the columns: id, token, cliente, contato,
        produto, problema, status, data_entrada.
        """
        # Parse query parameters
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        status_filter: str | None = None
        date_from: str | None = None
        date_to: str | None = None
        if 'status' in params:
            raw = params['status'][0].strip()
            status_filter = raw or None
        if 'start' in params:
            raw = params['start'][0].strip()
            date_from = raw or None
        if 'end' in params:
            raw = params['end'][0].strip()
            date_to = raw or None

        # Fetch orders with filters
        rows = fetch_orders(status_filter, date_from, date_to)

        # Build CSV content
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        # header
        writer.writerow(['id', 'token', 'cliente', 'contato', 'produto', 'problema', 'status', 'data_entrada'])
        for row in rows:
            writer.writerow(row)
        csv_data = output.getvalue()
        output.close()

        # Send as downloadable file
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        filename = 'ordens_servico.csv'
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(csv_data.encode('utf-8'))

    def _handle_order_update(self, token: str, form: dict):
        new_status = form.get('status', [''])[0]
        if new_status:
            update_order_status(token, new_status.strip())
            # redirect back to order page
        self.send_response(303)
        self.send_header('Location', f'/os/{token}')
        self.end_headers()

    def _qr_url(self, relative_path: str, size: int = 180) -> str:
        """
        Return the URL to generate a QR code for a given relative path.

        This implementation uses the goQR.me API (qrserver.com) instead of
        Google's deprecated chart API. The API accepts `data` and `size`
        parameters to produce a PNG image of the QR code. See the API
        documentation for details【610604762018612†L60-L75】.  This is necessary
        because Google's chart API for QR codes was deprecated and the
        endpoints now return 404 errors【408151768540813†L140-L146】.
        """
        # Build absolute URL for the current server so the QR encodes a valid link
        host = self.headers.get('Host') or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        # If host refers to localhost or loopback, attempt to use the machine's IP
        # so that QR codes are accessible from other devices on the same network.
        try:
            host_lower = host.split(':')[0].lower()
            if host_lower in ('localhost', '127.0.0.1', '0.0.0.0'):
                ip_addr = socket.gethostbyname(socket.gethostname())
                # Use same port as server
                host = f"{ip_addr}:{self.server.server_address[1]}"
        except Exception:
            # If resolving fails, keep the original host
            pass
        if relative_path.startswith('/'):
            url = f"http://{host}{relative_path}"
        else:
            url = f"http://{host}/{relative_path}"
        encoded = quote(url, safe='')
        # Use goQR.me's API: data=<encoded url>&size=<width>x<height>
        return f"https://api.qrserver.com/v1/create-qr-code/?data={encoded}&size={size}x{size}"

    def _send_html(self, data: bytes):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str = '0.0.0.0', port: int = 8000) -> None:
    init_db()
    server = HTTPServer((host, port), OSHandler)
    print(f"Servidor rodando em http://{host}:{port}/ (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Encerrando servidor...")
        server.server_close()


if __name__ == '__main__':
    run_server()