let opportunities = [];
let map;
let markers = [];
let currentFilter = 'all';
let currentSort = { column: 'date', direction: 'desc' };

async function initDashboard() {
    initMap();
    loadData();
    setupEventListeners();
}

function initMap() {
    map = L.map('map').setView([28.5421, -81.3723], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 19
    }).addTo(map);
}

async function loadData() {
    try {
        const response = await fetch('data.json');
        if (response.ok) {
            opportunities = await response.json();
        } else {
            opportunities = generateSampleData();
        }
        renderDashboard();
    } catch (error) {
        console.error('Error loading data:', error);
        opportunities = generateSampleData();
        renderDashboard();
    }
}

function generateSampleData() {
    return [
        {
            date: new Date().toISOString().split('T')[0],
            address: "123 Main St, Orlando, FL",
            latitude: 28.5421,
            longitude: -81.3723,
            margin: 35,
            profit: 45000,
            status: "Viável",
            arv: 250000,
            price: 155000,
            region: "Downtown"
        },
        {
            date: new Date(Date.now() - 86400000).toISOString().split('T')[0],
            address: "456 Oak Ave, Orlando, FL",
            latitude: 28.5521,
            longitude: -81.3823,
            margin: 28,
            profit: 38000,
            status: "Radar",
            arv: 240000,
            price: 172000,
            region: "Midtown"
        }
    ];
}

function renderDashboard() {
    updateSummary();
    renderTable();
    renderMap();
}

function updateSummary() {
    const total = opportunities.length;
    const viable = opportunities.filter(o => o.status === 'Viável').length;
    const radar = opportunities.filter(o => o.status === 'Radar').length;
    
    const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
    const newCount = opportunities.filter(o => o.date >= yesterday).length;
    
    const bestMarginOpp = opportunities.reduce((max, o) => (o.margin > (max?.margin || 0) ? o : max), null);
    const bestMargin = bestMarginOpp?.margin || 0;
    
    const dates = opportunities.map(o => new Date(o.date)).sort((a, b) => b - a);
    const lastCapture = dates[0]?.toLocaleDateString() || 'N/A';
    
    document.getElementById('totalCount').textContent = total;
    document.getElementById('viableCount').textContent = viable;
    document.getElementById('radarCount').textContent = radar;
    document.getElementById('newCount').textContent = newCount;
    document.getElementById('bestMargin').textContent = bestMargin + '%';
    document.getElementById('lastCapture').textContent = lastCapture;
}

function renderTable() {
    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = '';
    
    let filteredData = opportunities;
    if (currentFilter !== 'all') {
        filteredData = opportunities.filter(o => o.status.toLowerCase() === currentFilter.toLowerCase());
    }
    
    filteredData.sort((a, b) => {
        const aVal = a[currentSort.column];
        const bVal = b[currentSort.column];
        return currentSort.direction === 'asc' ? aVal - bVal : bVal - aVal;
    });
    
    filteredData.forEach(opp => {
        const row = document.createElement('tr');
        const statusClass = `status-${opp.status.toLowerCase()}`;
        row.innerHTML = `
            <td>${opp.date}</td>
            <td>${opp.address}</td>
            <td>${opp.margin}%</td>
            <td>$${opp.profit.toLocaleString()}</td>
            <td><span class="status-badge ${statusClass}">${opp.status}</span></td>
            <td>$${opp.arv.toLocaleString()}</td>
            <td>$${opp.price.toLocaleString()}</td>
        `;
        tbody.appendChild(row);
    });
}

function renderMap() {
    markers.forEach(marker => map.removeLayer(marker));
    markers = [];
    
    opportunities.forEach(opp => {
        let color = '#10b981';
        if (opp.status === 'Radar') color = '#f59e0b';
        else if (opp.status === 'Reprovada') color = '#ef4444';
        
        const marker = L.circleMarker([opp.latitude, opp.longitude], {
            radius: 10,
            fillColor: color,
            color: color,
            weight: 2,
            opacity: 0.8,
            fillOpacity: 0.7
        }).addTo(map);
        
        marker.bindPopup(`${opp.address}<br>Status: ${opp.status}<br>Margin: ${opp.margin}%`);
        markers.push(marker);
    });
}

function setupEventListeners() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.dataset.filter;
            renderTable();
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDashboard);
} else {
    initDashboard();
}