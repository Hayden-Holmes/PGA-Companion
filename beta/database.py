import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def create_tables(conn, schema_file):
    with open(schema_file, 'r') as f:
        schema_sql = f.read()
    
    cur = conn.cursor()
    cur.executescript(schema_sql)
    conn.commit()

conn = sqlite3.connect('golf.db')

schema_path = os.path.join(BASE_DIR, "schema.sql")

create_tables(conn, schema_path)
create_tables(conn, 'schema.sql')
