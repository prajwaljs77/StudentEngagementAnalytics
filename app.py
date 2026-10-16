"""Entry point:  python app.py   (or: flask --app app run)"""
import os

from backend import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
