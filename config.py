import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your_secret_key' # Keep your secret key secure
    DATABASE_DRIVER = '{ODBC Driver 13 for SQL Server}'
    DATABASE_SERVER = 'pgt3messqlods.fs.local'
    DATABASE_NAME = 'ODS'
    DATABASE_CONNECTION_STRING = f'DRIVER={DATABASE_DRIVER};SERVER={DATABASE_SERVER};DATABASE={DATABASE_NAME};Trusted_Connection=yes;'
    ALL_TOOLS = ["bussing", "frame", "dst", "duocam", "lf", "post_station", "pre_station"]
    IMAGE_BASE_URL = "http://pgt3messf.mfg.fs:19081/ImageDataMartApplication/ImageDataMart/images/"

# For the trends route, if it needs a specific list of tools
TRENDS_TOOLS = ["frame", "Silicon"] # Added "Silicon" as it's handled in the trends route