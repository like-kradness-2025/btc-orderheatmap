WSL quickstart:

1) deps
- Node.js 20+
- Python 3.11+
- pip install numpy pandas matplotlib aiohttp pytz requests

2) receiver
chmod +x ./run_receiver.sh
./run_receiver.sh btcusdt ./data/live 0

3) plot
chmod +x ./run_plot.sh
./run_plot.sh ./data/live ./tmp/chart.png 8
