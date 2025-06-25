import sqlite3
con =  sqlite3.connect(":memory:")
cur = con.cursor()

#테이블 생성
cur.execute("create table if not exists person " +
            "(id integer primary key autoincrement, name text, phoneNum text);")

#데이터 입력
cur.execute("insert into person (name, phoneNum) values (?, ?);",
       ("홍길동", "010-1234-5678"))

#입력 파라메터 처리: GUI화면에서 별도 입력
name = "전우치"
phoneNum = "010-9876-5432"
cur.execute("insert into person (name, phoneNum) values (?, ?);", (name, phoneNum))

#다중의 레코드를 입력
datalist = (("이순신", "010-1111-2222"),("강감찬", "010-3333-4444"))
cur.executemany("insert into person (name, phoneNum) values (?, ?);", datalist)


#데이터 조회
cur.execute("select * from person;")
for row in cur:
    print(row)

