import psycopg2
import os
from datetime import datetime

class DBService:
    def __init__(self):
        self.dbname = os.environ.get("DB_NAME", "IE")
        self.user = os.environ.get("DB_USER", "tarchunk")
        self.password = os.environ.get("DB_PASSWORD", "")
        self.host = os.environ.get("DB_HOST", "192.168.1.44")
        self.port = os.environ.get("DB_PORT", "5432")

    def get_connection(self):
        return psycopg2.connect(
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port
        )

    def create_table(self):
        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    amount VARCHAR(50),
                    date VARCHAR(50),
                    description TEXT,
                    type_of_ie VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            cur.close()
            print("Table 'transactions' check/creation successful.")
        except Exception as e:
            print(f"Error creating table: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def insert_transaction(self, amount, date, description, type_of_ie):
        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO transactions (amount, date, description, type_of_ie)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
            """, (amount, date, description, type_of_ie))
            
            txn_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            print(f"Transaction inserted with ID: {txn_id}")
            return txn_id
        except Exception as e:
            print(f"Error inserting transaction: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                conn.close()

if __name__ == "__main__":
    db = DBService()
    db.create_table()