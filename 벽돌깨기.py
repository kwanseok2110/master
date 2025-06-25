# brick_breaker.py
import pygame
import sys
import random

# 게임 설정
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
BRICK_ROWS = 5
BRICK_COLS = 10
BRICK_WIDTH = 70
BRICK_HEIGHT = 30
PADDLE_WIDTH = 100
PADDLE_HEIGHT = 15
BALL_RADIUS = 10

# 색상
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (0, 102, 204)
RED = (255, 0, 0)
GREEN = (0, 255, 0)

class Brick(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((BRICK_WIDTH, BRICK_HEIGHT))
        self.image.fill(BLUE)
        self.rect = self.image.get_rect(topleft=(x, y))

class Paddle(pygame.sprite.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pygame.Surface((PADDLE_WIDTH, PADDLE_HEIGHT))
        self.image.fill(GREEN)
        self.rect = self.image.get_rect(midbottom=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30))
        self.speed = 8

    def update(self):
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT] and self.rect.left > 0:
            self.rect.x -= self.speed
        if keys[pygame.K_RIGHT] and self.rect.right < SCREEN_WIDTH:
            self.rect.x += self.speed

class Ball(pygame.sprite.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pygame.Surface((BALL_RADIUS*2, BALL_RADIUS*2), pygame.SRCALPHA)
        pygame.draw.circle(self.image, RED, (BALL_RADIUS, BALL_RADIUS), BALL_RADIUS)
        self.rect = self.image.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
        self.dx = random.choice([-4, 4])
        self.dy = -4

    def update(self):
        self.rect.x += self.dx
        self.rect.y += self.dy

        # 벽 충돌
        if self.rect.left <= 0 or self.rect.right >= SCREEN_WIDTH:
            self.dx *= -1
        if self.rect.top <= 0:
            self.dy *= -1

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("양관석이 만든 Brick Breaker Game")
    clock = pygame.time.Clock()

    # 스프라이트 그룹
    all_sprites = pygame.sprite.Group()
    bricks = pygame.sprite.Group()

    # 벽돌 생성
    for row in range(BRICK_ROWS):
        for col in range(BRICK_COLS):
            brick = Brick(col * (BRICK_WIDTH + 5) + 35, row * (BRICK_HEIGHT + 5) + 40)
            all_sprites.add(brick)
            bricks.add(brick)

    paddle = Paddle()
    ball = Ball()
    all_sprites.add(paddle)
    all_sprites.add(ball)

    running = True
    game_over = False

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        if not game_over:
            all_sprites.update()

            # 패들 충돌
            if ball.rect.colliderect(paddle.rect):
                ball.dy *= -1
                ball.rect.bottom = paddle.rect.top

            # 벽돌 충돌
            hit_brick = pygame.sprite.spritecollideany(ball, bricks)
            if hit_brick:
                ball.dy *= -1
                hit_brick.kill()

            # 바닥에 닿으면 게임 오버
            if ball.rect.top > SCREEN_HEIGHT:
                game_over = True

            # 모든 벽돌 제거 시 게임 클리어
            if not bricks:
                game_over = True

        # 화면 그리기
        screen.fill(BLACK)
        all_sprites.draw(screen)

        if game_over:
            font = pygame.font.SysFont(None, 60)
            if not bricks:
                msg = font.render("CLEAR!", True, WHITE)
            else:
                msg = font.render("GAME OVER", True, WHITE)
            rect = msg.get_rect(center=(SCREEN_WIDTH//2, SCREEN_HEIGHT//2))
            screen.blit(msg, rect)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()