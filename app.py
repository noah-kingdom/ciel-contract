from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "<h1>🏰 CIEL-CONTRACT - Noah Kingdom</h1><p>AI Contract Analysis System</p>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)S
