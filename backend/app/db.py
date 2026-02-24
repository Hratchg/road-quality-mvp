import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://rq:rqpass@localhost:5432/roadquality"
)


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
