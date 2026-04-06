// Inovatech OS front-end script

const statusColors = {
  'Recebido': '#28a745',
  'Em análise': '#ffc107',
  'Aguardando aprovação': '#fd7e14',
  'Em execução': '#d63384',
  'Pronto': '#0d6efd'
};

// Current filter state
let filterState = {
  status: '',
  start: '',
  end: ''
};

document.addEventListener('DOMContentLoaded', () => {
  renderApp();
  fetchAndRenderOrders();
});

function renderApp() {
  const app = document.getElementById('app');
  // Build filter form
  const statusOptions = ['','Recebido','Em análise','Aguardando aprovação','Em execução','Pronto'];
  let statusSelectOptions = statusOptions.map(opt => {
    const selected = (opt === filterState.status) ? 'selected' : '';
    const label = opt === '' ? 'Todos' : opt;
    return `<option value="${opt}" ${selected}>${label}</option>`;
  }).join('');
  const filterHTML = `
    <form id="filterForm" class="row g-2 mb-3">
      <div class="col-auto">
        <label for="statusFilter" class="col-form-label">Status:</label>
      </div>
      <div class="col-auto">
        <select class="form-select" id="statusFilter" name="status">
          ${statusSelectOptions}
        </select>
      </div>
      <div class="col-auto">
        <label for="startDate" class="col-form-label">Data inicial:</label>
      </div>
      <div class="col-auto">
        <input type="date" class="form-control" id="startDate" name="start" value="${filterState.start}">
      </div>
      <div class="col-auto">
        <label for="endDate" class="col-form-label">Data final:</label>
      </div>
      <div class="col-auto">
        <input type="date" class="form-control" id="endDate" name="end" value="${filterState.end}">
      </div>
      <div class="col-auto">
        <button type="submit" class="btn btn-primary">Aplicar</button>
      </div>
    </form>
  `;
  // Build new order form (hidden by default)
  const newOrderCard = `
    <div id="newOrderSection" class="card mb-3 d-none">
      <div class="card-header">Nova Ordem de Serviço</div>
      <div class="card-body">
        <form id="newOrderForm" class="row g-3">
          <div class="col-md-6">
            <label for="cliente" class="form-label">Cliente</label>
            <input type="text" class="form-control" id="cliente" name="cliente" required>
          </div>
          <div class="col-md-6">
            <label for="contato" class="form-label">Contato</label>
            <input type="text" class="form-control" id="contato" name="contato" required>
          </div>
          <div class="col-md-6">
            <label for="produto" class="form-label">Produto/Equipamento</label>
            <input type="text" class="form-control" id="produto" name="produto" required>
          </div>
          <div class="col-md-12">
            <label for="problema" class="form-label">Descrição do problema</label>
            <textarea class="form-control" id="problema" name="problema" rows="2" required></textarea>
          </div>
          <div class="col-md-6">
            <label for="status" class="form-label">Status inicial</label>
            <select class="form-select" id="status" name="status">
              <option value="Recebido">Recebido</option>
              <option value="Em análise">Em análise</option>
              <option value="Aguardando aprovação">Aguardando aprovação</option>
              <option value="Em execução">Em execução</option>
              <option value="Pronto">Pronto</option>
            </select>
          </div>
          <div class="col-12">
            <button type="submit" class="btn btn-success">Salvar</button>
            <button type="button" id="cancelNewOrderBtn" class="btn btn-link">Cancelar</button>
          </div>
        </form>
      </div>
    </div>
  `;
  // Build orders container placeholder
  const ordersContainer = `<div id="ordersContainer"></div>`;
  // Build legend
  const legendItems = Object.entries(statusColors).map(([label, color]) => {
    return `<span class="d-inline-flex align-items-center me-3"><span style="width:12px;height:12px;border-radius:50%;background:${color};display:inline-block;margin-right:4px;"></span>${label}</span>`;
  }).join('');
  const legendHTML = `
    <div class="mt-4 pt-3 border-top">
      <h6>Guia de cores</h6>
      ${legendItems}
    </div>
  `;
  // Build export link placeholder (will be updated when rendering orders)
  const exportPlaceholder = `<div id="exportContainer" class="mb-3"></div>`;
  // Build button to show the new order form
  const newOrderButton = `
    <div class="mb-3">
      <button id="showNewOrderBtn" class="btn btn-primary">Nova Ordem</button>
    </div>
  `;
  app.innerHTML = filterHTML + newOrderButton + newOrderCard + exportPlaceholder + ordersContainer + legendHTML;
  // Attach event listeners
  const filterForm = document.getElementById('filterForm');
  filterForm.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const formData = new FormData(filterForm);
    filterState.status = formData.get('status') || '';
    filterState.start = formData.get('start') || '';
    filterState.end = formData.get('end') || '';
    fetchAndRenderOrders();
  });
  const newForm = document.getElementById('newOrderForm');
  newForm.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const formData = new FormData(newForm);
    const params = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      params.append(key, value);
    }
    fetch('/api/orders', {
      method: 'POST',
      body: params
    })
    .then(resp => resp.json())
    .then(data => {
      // Clear form
      newForm.reset();
      // Hide the new order section
      document.getElementById('newOrderSection').classList.add('d-none');
      fetchAndRenderOrders();
    })
    .catch(err => console.error(err));
  });

  // Show new order form button
  const showBtn = document.getElementById('showNewOrderBtn');
  showBtn.addEventListener('click', () => {
    const section = document.getElementById('newOrderSection');
    section.classList.toggle('d-none');
  });
  // Cancel new order button inside form
  const cancelBtn = document.getElementById('cancelNewOrderBtn');
  cancelBtn.addEventListener('click', () => {
    document.getElementById('newOrderSection').classList.add('d-none');
    newForm.reset();
  });
}

function fetchAndRenderOrders() {
  // Build query string
  const params = [];
  if (filterState.status) params.push(`status=${encodeURIComponent(filterState.status)}`);
  if (filterState.start) params.push(`start=${encodeURIComponent(filterState.start)}`);
  if (filterState.end) params.push(`end=${encodeURIComponent(filterState.end)}`);
  const qs = params.length ? '?' + params.join('&') : '';
  fetch('/api/orders' + qs)
    .then(resp => resp.json())
    .then(data => {
      renderOrdersList(data.orders || []);
      renderExportLink();
    })
    .catch(err => {
      console.error(err);
      // Show a message in the orders container when the API cannot be reached, e.g. when the server is not running
      const container = document.getElementById('ordersContainer');
      if (container) {
        container.innerHTML = '<div class="alert alert-danger" role="alert">Erro ao carregar dados. Certifique-se de que o servidor está em execução e você acessou esta página via <code>http://.../index.html</code>.</div>';
      }
    });
}

function renderOrdersList(orders) {
  const container = document.getElementById('ordersContainer');
  if (!orders || orders.length === 0) {
    container.innerHTML = '<p class="text-center">Nenhuma ordem cadastrada.</p>';
    return;
  }
  // Build table
  let rows = orders.map(order => {
    const date = new Date(order.data_entrada);
    const dateStr = date.toLocaleString('pt-BR');
    const color = statusColors[order.status] || '#000';
    // Build QR url using current location host
    const host = window.location.host;
    const detailUrl = `${window.location.protocol}//${host}/os/${order.token}`;
    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent(detailUrl)}&size=80x80`;
    // Build status select
    const statusOptions = ['Recebido','Em análise','Aguardando aprovação','Em execução','Pronto'].map(opt => {
      const selected = (opt === order.status) ? 'selected' : '';
      return `<option value="${opt}" ${selected}>${opt}</option>`;
    }).join('');
    return `
      <tr>
        <td>${order.id}</td>
        <td>${order.cliente}</td>
        <td>${order.produto}</td>
        <td><span style="color:${color};font-weight:600;">${order.status}</span></td>
        <td>${dateStr}</td>
        <td><a href="/os/${order.token}" target="_blank"><img src="${qrUrl}" alt="QR" style="width:40px;height:40px;"></a></td>
        <td>
          <select class="form-select form-select-sm" data-token="${order.token}">
            ${statusOptions}
          </select>
          <button class="btn btn-sm btn-outline-primary mt-1" data-token="${order.token}">Atualizar</button>
        </td>
      </tr>
    `;
  }).join('');
  const tableHtml = `
    <table class="table table-striped table-bordered">
      <thead class="table-light">
        <tr>
          <th>ID</th><th>Cliente</th><th>Produto</th><th>Status</th><th>Entrada</th><th>QR Code</th><th>Ações</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
  container.innerHTML = tableHtml;
  // Attach event listeners for update buttons
  container.querySelectorAll('button[data-token]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      const token = btn.getAttribute('data-token');
      const select = container.querySelector(`select[data-token="${token}"]`);
      const newStatus = select.value;
      const params = new URLSearchParams();
      params.append('status', newStatus);
      fetch(`/api/orders/${token}/status`, {
        method: 'POST',
        body: params
      })
      .then(resp => resp.json())
      .then(() => {
        fetchAndRenderOrders();
      })
      .catch(err => console.error(err));
    });
  });
}

function renderExportLink() {
  const exportContainer = document.getElementById('exportContainer');
  const params = [];
  if (filterState.status) params.push(`status=${encodeURIComponent(filterState.status)}`);
  if (filterState.start) params.push(`start=${encodeURIComponent(filterState.start)}`);
  if (filterState.end) params.push(`end=${encodeURIComponent(filterState.end)}`);
  const qs = params.length ? '?' + params.join('&') : '';
  exportContainer.innerHTML = `<a class="btn btn-outline-secondary" href="/export${qs}">Exportar CSV</a>`;
}
