import sqlite3
import random

class ElectronicsDB:
    def __init__(self, db_name="electronics.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_table()

    def create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        )
        """
        self.conn.execute(query)
        self.conn.commit()

    def insert_product(self, name, price):
        query = "INSERT INTO products (name, price) VALUES (?, ?)"
        self.conn.execute(query, (name, price))
        self.conn.commit()

    def update_product(self, product_id, name, price):
        query = "UPDATE products SET name=?, price=? WHERE id=?"
        self.conn.execute(query, (name, price, product_id))
        self.conn.commit()

    def delete_product(self, product_id):
        query = "DELETE FROM products WHERE id=?"
        self.conn.execute(query, (product_id,))
        self.conn.commit()

    def select_all(self):
        query = "SELECT * FROM products"
        cursor = self.conn.execute(query)
        return cursor.fetchall()

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    db = ElectronicsDB()

    # 샘플 데이터 100개 입력
    sample_names = ["노트북", "스마트폰", "태블릿", "TV", "이어폰", "스피커", "마우스", "키보드", "모니터", "프린터"]
    for i in range(1, 101):
        name = f"{random.choice(sample_names)}_{i}"
        price = random.randint(50000, 2000000)
        db.insert_product(name, price)

    # 전체 데이터 조회
    products = db.select_all()
    for product in products[:99]:  # 앞 10개만 출력
        print(product)

    # 제품 수정 예시
    db.update_product(1, "수정된제품", 123456)

    # 제품 삭제 예시
    db.delete_product(2)

    db.close()