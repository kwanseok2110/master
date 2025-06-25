import pygame
import sys
from game import Game

def main():
    pygame.init()
    
    # Set up the game window
    screen_width = 800
    screen_height = 600
    screen = pygame.display.set_mode((screen_width, screen_height))
    pygame.display.set_caption("Brick Breaker Game")
    
    # Create a Game instance
    game = Game(screen)
    
    # Game loop
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
        
        game.update()
        game.render()
        
        pygame.display.flip()
        pygame.time.Clock().tick(60)

if __name__ == "__main__":
    main()