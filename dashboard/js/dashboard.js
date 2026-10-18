// Hermes Trading Dashboard - Main Script
class HermesDashboard {
  constructor() {
    this.currentTheme = localStorage.getItem('theme') || 'dark';
    this.updateInterval = null;
    this.charts = {};
    
    this.init();
  }

  init() {
    this.setupTheme();
    this.bindEvents();
    this.initCharts();
    this.startAutoUpdate();
    this.loadInitialData();
  }

  setupTheme() {
    document.documentElement.setAttribute('data-theme', this.currentTheme);
    const toggleBtn = document.getElementById('themeToggle');
    const icon = toggleBtn.querySelector('i');
    
    if (this.currentTheme === 'light') {
      icon.className = 'fas fa-sun';
    }
  }

  bindEvents() {
    // Theme toggle
    document.getElementById('themeToggle').addEventListener('click', () => {
      this.toggleTheme();
    });

    // Time filters
    document.querySelectorAll('.time-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        document.querySelector('.time-btn.active').classList.remove('active');
        e.target.classList.add('active');
        this.updateChartData(e.target.dataset.period);
      });
    });
  }

  toggleTheme() {
    this.currentTheme = this.currentTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', this.currentTheme);
    document.documentElement.setAttribute('data-theme', this.currentTheme);
    
    const icon = document.querySelector('#themeToggle i');
    icon.className = this.currentTheme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
  }

  initCharts() {
    // Equity Curve Chart
    const equityCtx = document.getElementById('equityChart').getContext('2d');
    this.charts.equity = new Chart(equityCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Performance %',
          data: [],
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)',
          borderWidth: 3,
          fill: true,
          tension: 0.3,
          pointRadius: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          }
        },
        scales: {
          y: {
            grid: {
              color: 'rgba(68, 75, 88, 0.5)'
            },
            ticks: {
              color: 'var(--text-secondary)'
            }
          },
          x: {
            grid: {
              display: false
            },
            ticks: {
              color: 'var(--text-secondary)'
            }
          }
        }
      }
    });

    // Strategy Performance Chart
    const strategyCtx = document.getElementById('strategyChart').getContext('2d');
    this.charts.strategy = new Chart(strategyCtx, {
      type: 'bar',
      data: {
        labels: ['Breakout', 'Mean Reversion', 'Turtle', 'CANSLIM'],
        datasets: [{
          label: 'Performance %',
          data: [12.5, 8.3, 15.2, 6.7],
          backgroundColor: [
            '#10b981',
            '#3b82f6',
            '#f59e0b',
            '#8b5cf6'
          ],
          borderRadius: 5
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          }
        },
        scales: {
          y: {
            grid: {
              color: 'rgba(68, 75, 88, 0.5)'
            },
            ticks: {
              color: 'var(--text-secondary)'
            }
          },
          x: {
            grid: {
              display: false
            },
            ticks: {
              color: 'var(--text-secondary)'
            }
          }
        }
      }
    });
  }

  async loadInitialData() {
    try {
      // Load portfolio data
      const portfolioRes = await fetch('/api/v1/portfolio');
      const portfolio = await portfolioRes.json();
      this.updatePortfolioDisplay(portfolio);
      
      // Load open positions
      const positionsRes = await fetch('/api/v1/positions');
      const positions = await positionsRes.json();
      this.updatePositionsDisplay(positions);
      
      // Load recent trades
      const tradesRes = await fetch('/api/v1/trades/recent?limit=10');
      const trades = await tradesRes.json();
      this.updateTradesDisplay(trades);
      
      // Load market watch
      const marketRes = await fetch('/api/v1/market/watch');
      const market = await marketRes.json();
      this.updateMarketWatch(market);
      
      // Update timestamp
      document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
      
    } catch (error) {
      console.error('Error loading initial data:', error);
      this.updateConnectionStatus(false);
    }
  }

  updatePortfolioDisplay(data) {
    document.getElementById('portfolioValue').textContent = `€${data.balance.toFixed(2)}`;
    const changeElement = document.getElementById('portfolioChange');
    const changePercent = data.change_percent;
    changeElement.textContent = changePercent >= 0 ? `+${changePercent.toFixed(1)}%` : `${changePercent.toFixed(1)}%`;
    changeElement.className = `stat-change ${changePercent >= 0 ? 'positive' : 'negative'}`;
  }

  updatePositionsDisplay(positions) {
    const container = document.getElementById('positionsList');
    const countElement = document.getElementById('openPositionsCount');
    
    countElement.textContent = positions.length;
    
    container.innerHTML = positions.map(pos => `
      <div class="position-item ${pos.direction.toLowerCase()}">
        <div class="position-header">
          <span class="position-symbol">${pos.symbol}</span>
          <span class="position-direction ${pos.direction === 'LONG' ? 'direction-long' : 'direction-short'}">
            ${pos.direction}
          </span>
        </div>
        <div class="position-details">
          <div><span class="detail-label">Entrée</span><span class="detail-value">${pos.entry_price.toFixed(2)}</span></div>
          <div><span class="detail-label">Actuel</span><span class="detail-value">${pos.current_price.toFixed(2)}</span></div>
          <div><span class="detail-label">P&L</span><span class="detail-value ${pos.pnl >= 0 ? 'positive' : 'negative'}">€${Math.abs(pos.pnl).toFixed(2)}</span></div>
        </div>
      </div>
    `).join('');
  }

  updateTradesDisplay(trades) {
    const container = document.getElementById('tradesList');
    container.innerHTML = trades.map(trade => `
      <div class="trade-item">
        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
          <span class="position-symbol">${trade.symbol}</span>
          <span class="position-direction ${trade.result >= 0 ? 'direction-long' : 'direction-short'}">
            ${trade.result >= 0 ? '✅ Gagnant' : '❌ Perdant'}
          </span>
        </div>
        <div class="position-details">
          <div><span class="detail-label">Stratégie</span><span class="detail-value">${trade.strategy}</span></div>
          <div><span class="detail-label">Résultat</span><span class="detail-value ${trade.result >= 0 ? 'positive' : 'negative'}">€${trade.result.toFixed(2)}</span></div>
          <div><span class="detail-label">Date</span><span class="detail-value">${new Date(trade.timestamp).toLocaleDateString()}</span></div>
        </div>
      </div>
    `).join('');
  }

  updateMarketWatch(data) {
    const container = document.getElementById('marketWatch');
    container.innerHTML = data.map(item => `
      <div class="market-watch-item">
        <span class="market-pair">${item.symbol}</span>
        <span class="market-change ${item.change >= 0 ? 'change-positive' : 'change-negative'}">
          ${item.change >= 0 ? '▲' : '▼'} ${Math.abs(item.change).toFixed(2)}%
        </span>
      </div>
    `).join('');
  }

  updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connectionStatus');
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('span');
    
    if (connected) {
      dot.className = 'status-dot connected';
      text.textContent = 'Connecté';
    } else {
      dot.className = 'status-dot disconnected';
      text.textContent = 'Déconnecté';
    }
  }

  updateChartData(period) {
    // Mettre à jour les graphiques avec les données du period sélectionné
    console.log(`Updating charts for period: ${period}`);
  }

  startAutoUpdate() {
    this.updateInterval = setInterval(() => {
      this.loadInitialData();
    }, 5000); // Mise à jour toutes les 5 secondes
  }
}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new HermesDashboard();
});