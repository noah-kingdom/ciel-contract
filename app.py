import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "<h1>🏰 CIEL-CONTRACT - Noah Kingdom</h1><p>AI Contract Analysis System</p><p>Noah王国の技術基盤、完全復活！</p>"

if __name__ == '__main__':
    # Azure App Serviceでは環境変数PORTが設定される
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
