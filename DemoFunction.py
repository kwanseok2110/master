#DemoFunction.py

#함수를 정의
def setValue(newValue):
    #지역변수
    x = newValue
    print("함수 내부:", x)

#함수를 호출
result = setValue(5)
print(result)

#함수를 정의
def swap(x,y):
    return y,x

result = swap(3,4)
print(result)