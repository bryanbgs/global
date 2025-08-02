# m3u_generator.py
from app import generate_m3u
from flask import Flask

app = Flask(__name__)
app.register_blueprint(app.blueprints.get('main', __name__))

if __name__ == "__main__":
    with app.test_request_context():
        m3u = generate_m3u().get_data(as_text=True)
        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write(m3u)
        print("✅ Lista M3U generada: playlist.m3u")
