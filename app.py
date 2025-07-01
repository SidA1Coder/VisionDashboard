from flask import Flask
from .config import Config
from .blueprints.auth_routes import auth_bp
from .blueprints.data_input_routes import data_input_bp
from .blueprints.trends_routes import trends_bp
# Remove direct imports of pyodbc, struct, traceback, requests, PIL, BytesIO, base64,
# cairosvg, io, plotly, pandas, json, numpy as they are now used in sub-modules.
# to run this app **cd .. ***** python -m Vision.app *** 
def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(data_input_bp)
    app.register_blueprint(trends_bp)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True) # debug=True is fine for development