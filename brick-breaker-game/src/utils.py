def draw_rectangle(surface, color, rect):
    import pygame
    pygame.draw.rect(surface, color, rect)

def check_collision(rect1, rect2):
    return rect1.collidereect(rect2)

def load_image(file_path):
    import pygame
    return pygame.image.load(file_path)

def display_message(surface, message, position, font_size=30, color=(255, 255, 255)):
    import pygame
    font = pygame.font.Font(None, font_size)
    text = font.render(message, True, color)
    surface.blit(text, position)

def reset_game_settings():
    return {
        "score": 0,
        "lives": 3,
        "level": 1
    }