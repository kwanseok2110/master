import tkinter as tk
import random

# 게임 설정
WIDTH = 400
HEIGHT = 400
SEG_SIZE = 20
INIT_LENGTH = 3
DELAY = 100  # ms

# 방향 상수
DIRECTIONS = {
    "Left": (-1, 0),
    "Right": (1, 0),
    "Up": (0, -1),
    "Down": (0, 1)
}

class SnakeGame:
    def __init__(self, master):
        self.master = master
        self.canvas = tk.Canvas(master, width=WIDTH, height=HEIGHT, bg="black")
        self.canvas.pack()
        self.direction = "Right"
        self.snake = []
        self.food = None
        self.running = False  # 처음엔 멈춤 상태
        self.score = 0
        self.score_text = self.canvas.create_text(10, 10, anchor="nw", text="점수: 0", fill="white", font=("Arial", 14))

        # 초기 뱀 생성
        for i in range(INIT_LENGTH):
            x = SEG_SIZE * (INIT_LENGTH - i - 1)
            y = 0
            seg = self.canvas.create_rectangle(x, y, x + SEG_SIZE, y + SEG_SIZE, fill="green")
            self.snake.append(seg)

        self.create_food()
        self.master.bind("<KeyPress>", self.on_key_press)
        self.start_msg = self.canvas.create_text(WIDTH // 2, HEIGHT // 2, text="스페이스바를 눌러 시작!", fill="white", font=("Arial", 18))

    def start_game(self):
        if not self.running:
            self.running = True
            self.canvas.delete("all")
            self.snake.clear()
            self.direction = "Right"
            self.score = 0
            self.score_text = self.canvas.create_text(10, 10, anchor="nw", text="점수: 0", fill="white", font=("Arial", 14))
            # 초기 뱀 생성
            for i in range(INIT_LENGTH):
                x = SEG_SIZE * (INIT_LENGTH - i - 1)
                y = 0
                seg = self.canvas.create_rectangle(x, y, x + SEG_SIZE, y + SEG_SIZE, fill="green")
                self.snake.append(seg)
            self.create_food()
            self.move_snake()

    def create_food(self):
        while True:
            x = random.randint(0, (WIDTH - SEG_SIZE) // SEG_SIZE) * SEG_SIZE
            y = random.randint(0, (HEIGHT - SEG_SIZE) // SEG_SIZE) * SEG_SIZE
            overlap = self.canvas.find_overlapping(x, y, x + SEG_SIZE, y + SEG_SIZE)
            if len(overlap) == 0:
                break
        self.food = self.canvas.create_rectangle(x, y, x + SEG_SIZE, y + SEG_SIZE, fill="red")

    def move_snake(self):
        if not self.running:
            return

        dx, dy = DIRECTIONS[self.direction]
        head_coords = self.canvas.coords(self.snake[0])
        new_head_x = head_coords[0] + dx * SEG_SIZE
        new_head_y = head_coords[1] + dy * SEG_SIZE

        # 벽 충돌 체크
        if (new_head_x < 0 or new_head_x >= WIDTH or
            new_head_y < 0 or new_head_y >= HEIGHT):
            self.game_over()
            return

        # 자기 몸 충돌 체크
        for seg in self.snake:
            if self.canvas.coords(seg) == [new_head_x, new_head_y, new_head_x + SEG_SIZE, new_head_y + SEG_SIZE]:
                self.game_over()
                return

        # 이동
        new_head = self.canvas.create_rectangle(
            new_head_x, new_head_y,
            new_head_x + SEG_SIZE, new_head_y + SEG_SIZE,
            fill="green"
        )
        self.snake = [new_head] + self.snake

        # 먹이 먹었는지 체크
        if self.canvas.coords(new_head) == self.canvas.coords(self.food):
            self.canvas.delete(self.food)
            self.create_food()
            self.score += 1
            self.canvas.itemconfig(self.score_text, text=f"점수: {self.score}")
        else:
            tail = self.snake.pop()
            self.canvas.delete(tail)

        self.master.after(DELAY, self.move_snake)

    def on_key_press(self, event):
        if event.keysym == "space":
            self.start_game()
        elif event.keysym in DIRECTIONS and self.running:
            # 반대 방향으로는 이동 불가
            opposite = {"Left": "Right", "Right": "Left", "Up": "Down", "Down": "Up"}
            if opposite[event.keysym] != self.direction:
                self.direction = event.keysym

    def game_over(self):
        self.running = False
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2, text=f"Game Over\n점수: {self.score}\n스페이스바로 재시작", fill="white", font=("Arial", 24))

if __name__ == "__main__":
    root = tk.Tk()
    root.title("양관석이 만든 뱀게임 2025-06-24")
    game = SnakeGame(root)
    root.mainloop()