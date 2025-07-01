import pyodbc
import struct
from .config import Config

def handle_datetimeoffset(dto_value):
    """Handles datetimeoffset conversion for pyodbc."""
    tup = struct.unpack("<6hI2h", dto_value)
    tweaked = [tup[i] // 100 if i == 6 else tup[i] for i in range(len(tup))]
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}.{:07d} {:+03d}:{:02d}".format(*tweaked)

def get_db_connection():
    """Establishes and returns a database connection."""
    try:
        conn = pyodbc.connect(Config.DATABASE_CONNECTION_STRING)
        conn.add_output_converter(-155, handle_datetimeoffset)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

def query_database(query, args=(), one=False):
    """Executes a database query and returns results."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        return (rv[0] if rv else None) if one else rv
    except Exception as e:
        print(f"Error querying database: {e}")
        raise
    finally:
        if conn:
            conn.close()