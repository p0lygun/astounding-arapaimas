import json
import logging
import os.path
from copy import deepcopy

import appdirs
import httpx
from blessed import Terminal
from numpy import ones
from websocket import (
    WebSocket,
    WebSocketBadStatusException,
)

from app import ascii_art, constants
from app.chess import ChessBoard
from app.ui.Colour import ColourScheme

PIECES = "".join(chr(9812 + x) for x in range(12))
print(PIECES)
COL = ("A", "B", "C", "D", "E", "F", "G", "H")
ROW = tuple(map(str, range(1, 9)))

INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
initial_game = [
    ["r", "n", "b", "q", "k", "b", "n", "r"],
    ["p"] * 8,
    ["em"] * 8,
    ["em"] * 8,
    ["em"] * 8,
    ["em"] * 8,
    ["P"] * 8,
    ["R", "N", "B", "Q", "K", "B", "N", "R"],
]

BLACK_PIECES = ("r", "n", "b", "q", "k", "p")

WHITE_PIECES = ("R", "N", "B", "Q", "K", "P")

mapper = {
    "em": ("", "white"),
    "K": (PIECES[0], "white"),
    "Q": (PIECES[1], "white"),
    "R": (PIECES[2], "white"),
    "B": (PIECES[3], "white"),
    "N": (PIECES[4], "white"),
    "P": (PIECES[5], "white"),
    "k": (PIECES[6], "black"),
    "q": (PIECES[7], "black"),
    "r": (PIECES[8], "black"),
    "b": (PIECES[9], "black"),
    "n": (PIECES[10], "black"),
    "p": (PIECES[11], "black"),
}

log = logging.getLogger(__name__)


class Player:
    """Class for defining a player."""

    def __init__(self, token: str = None):
        self.token = token
        self.player_id = None
        self.game_history = None  # stores the result of the previous games


class Game:
    """
    Main class of the project.

    That will handle :-
       - the menus
       - connection with the server
       - printing of the chessboard
       - turns of players when playing locally
    """

    def __init__(self):
        self.term = Terminal()
        self.player = None
        self.game_id = None  # the game lobby id that the server will provide for online multiplayer
        self.local_testing = True
        self.server = "astounding-arapaimas-pr-38.up.railway.app"
        self.secure = "s"
        self.port = ""
        if self.local_testing:
            self.port = ":8000"
            self.server = "127.0.0.1"
            self.secure = ""
        self.headers = dict()
        self.web_socket = WebSocket()
        self.colour_scheme = "default"
        self.theme = ColourScheme(self.term, theme=self.colour_scheme)
        self.chess = ChessBoard(INITIAL_FEN)
        self.chess_board = self.fen_to_board(self.chess.give_board())
        self.fen = INITIAL_FEN
        self.tile_width = 6
        self.tile_height = 3
        self.offset_x = 0
        self.offset_y = 0
        self.x = 0
        self.y = 0
        # self.my_color = 'white' # for future
        self.white_move = True  # this will change in multiplayer game
        self.selected_row = 0
        self.selected_col = 0
        self.possible_moves = []
        self.moves_played = 0
        self.moves_limit = 1000  # TODO:: MAKE THIS DYNAMIC
        self.visible_layers = 8
        self.screen = "fullscreen"
        self.hidden_layer = ones((self.visible_layers, self.visible_layers))

    def __len__(self) -> int:
        return 8

    def ask_or_get_token(self) -> str:
        """
        Ask the user/get token from cache.

        If token is found in user's cache then read that else ask
        the user for the token, validate it through the API and store it
        in user's cache.
        """
        cache_path = f'{appdirs.user_cache_dir("stealth_chess")}/token.json'
        if os.path.exists(cache_path):
            # Read file token from file as cache exists
            with open(cache_path, "r", encoding="utf-8") as file:
                token = (json.load(file)).get("token")
                if token:
                    return token

        # If cache file is not found
        token_ok = False
        token = input("Enter your API token")
        while not token_ok:
            r = httpx.put(
                f"http{self.secure}://{self.server}{self.port}/validate_token",
                json={"token": token},
            )
            if r.status_code != 200:
                token = input("Invalid token, enter the correct one: ")
            else:
                token_ok = True

        token = {"token": token}  # ask token

        # Make the cache folder for storing the token
        directory = os.path.dirname(cache_path)
        if not os.path.exists(directory):
            os.makedirs(directory)

        # Write the token to cache file
        with open(cache_path, "w+", encoding="utf-8") as file:
            json.dump(token, file, ensure_ascii=False, indent=4)
        return token["token"]

    def create_lobby(self) -> str:
        """Used to create a game lobby on the server or locally."""
        if not self.game_id:
            try:
                httpx.get(f"http{self.secure}://{self.server}{self.port}/")
            except httpx.ConnectError:
                return f"{self.term.blink}Can't connect to  {self.server}"
            # server up
            try:
                token = self.ask_or_get_token()
            except KeyboardInterrupt:
                return "BACK"
            self.player = Player(token)
            # get the game id
            self.headers.update({"Authorization": f"Bearer {self.player.token}"})
            try:
                resp = httpx.get(
                    f"http{self.secure}://{self.server}{self.port}/game/new",
                    headers=self.headers,
                )
                if resp.status_code != 200:
                    raise httpx.HTTPError
                self.game_id = resp.json()["room"]
                return "New lobby created Press [ENTER] to continue"
            except httpx.HTTPError:
                return f"server returned Error code {resp.status_code}"
        else:
            return "Restart Game ..."

    def connect_to_lobby(self) -> str:
        """Connect to a lobby after Creating one or with game_id."""
        if not self.game_id:
            self.game_id = input("Enter Game id :- ").strip()
        if not self.player:
            self.player = Player(self.ask_or_get_token())
            self.headers = {"Authorization": f"Bearer {self.player.token}"}
        ws_url = f"ws{self.secure}://{self.server}{self.port}/game/{self.game_id}"
        data = ""
        try:

            self.web_socket.connect(ws_url, header=self.headers)
            data = "INFO::INIT"
            print(self.term.home + self.theme.background + self.term.clear)
            print(f"lobby id :- {self.game_id}")
            print("Waiting for all players to connect ....")

            while data[1] != "READY":

                data = self.web_socket.recv().split("::")
                if data[1] == "PLAYER":  # INFO::PLAYER::p1
                    self.player.player_id = int(data[2][-1])
                    print(self.player.player_id)
            return "READY"

        except WebSocketBadStatusException:
            return "Sever Error pls.. Try Again...."
        except Exception:
            log.error(f"{data} {ws_url}")
            raise

    def show_welcome_screen(self) -> str:
        """Prints startup screen and return pressed key."""
        with self.term.cbreak():
            print(self.term.home + self.theme.background + self.term.clear)
            # draw bottom chess pieces
            padding = (
                self.term.width
                - sum(
                    max(len(p) for p in piece.split("\n"))
                    for piece in constants.GAME_WELCOME_TOP
                )
            ) // 2
            position = 0
            for piece in constants.GAME_WELCOME_TOP:
                for i, val in enumerate(piece.split("\n")):
                    with self.term.location(
                        padding + position,
                        self.term.height - (len(piece.split("\n")) + 1) + i,
                    ):
                        print(self.theme.ws_bottom(val))
                position += max(len(p) for p in piece.split("\n"))

            # draw top chess pieces
            position = 0
            for piece in constants.GAME_WELCOME_BOTTOM:
                for i, val in enumerate(piece.split("\n")):
                    with self.term.location(padding + position, 1 + i):
                        print(self.theme.ws_top(val))
                position += max(len(p) for p in piece.split("\n"))

            # draw side characters
            for i, char in enumerate(ascii_art.FEN[: self.term.height - 2]):
                with self.term.location(0, 1 + i):
                    print(self.theme.ws_side_chars(char))
                with self.term.location(self.term.width, 1 + i):
                    print(self.theme.ws_side_chars(char))

            # draw box center message
            message = "PRESS ANY KEY TO START"
            padding = (self.term.width - len(message)) // 2
            with self.term.location(padding, self.term.height // 2):
                print(self.theme.ws_message(message))

            # draw THINK box
            padding = (self.term.width - len(ascii_art.THINK.split("\n")[0])) // 2
            for i, val in enumerate(ascii_art.THINK.split("\n")):
                with self.term.location(
                    5, self.term.height - len(ascii_art.THINK.split("\n")) + i
                ):
                    print(self.theme.ws_think(val))
            keypress = self.term.inkey()
            return keypress

    def show_game_menu(self) -> str:
        """Prints the game-menu screen."""

        def print_options() -> None:
            for i, option in enumerate(
                constants.MENU_MAPPING.items()
            ):  # updates the options
                title, (_, style, highlight) = option
                if i == self.curr_highlight:
                    print(
                        self.term.move_x(term_positions[i])
                        + getattr(self.theme, highlight)
                        + str(title)
                        + self.term.normal
                        + self.term.move_x(0),
                        end="",
                    )
                else:
                    print(
                        self.term.move_x(term_positions[i])
                        + getattr(self.theme, style)
                        + str(title)
                        + self.term.normal
                        + self.term.move_x(0),
                        end="",
                    )

            if self.curr_highlight != 9:
                print(
                    self.term.move_down(3)
                    + self.theme.gm_option_message
                    + self.term.center(
                        list(constants.MENU_MAPPING.values())[self.curr_highlight][0]
                    )
                    + self.term.move_x(0)
                    + "\n\n"
                    + self.term.white
                    + self.term.center("Press [ENTER] to confirm")
                    + self.term.move_up(5),
                    end="",
                )
            else:
                print(
                    self.term.move_down(3)
                    + self.term.white
                    + self.term.center("Press [TAB] for option selection")
                    + self.term.normal
                    + self.term.move_up(4)
                    + self.term.move_x(0)
                )

        def select_option() -> None:  # updates the highlighter variable
            if self.curr_highlight < 3:
                self.curr_highlight += 1
            else:
                self.curr_highlight = 0

        w, h = self.term.width, self.term.height

        self.curr_highlight = 9
        spacing = int(w * 0.05)
        padding = (
            w
            - sum(len(option) for option in constants.MENU_MAPPING.keys())
            - spacing * len(constants.MENU_MAPPING.keys())
        ) // 2
        position = padding
        term_positions = []
        for option in constants.MENU_MAPPING:
            term_positions.append(position)
            position += len(option) + spacing

        title_split = ascii_art.menu_logo.rstrip().split("\n")
        max_chars = len(max(title_split, key=len))
        with self.term.cbreak(), self.term.hidden_cursor():
            print(self.term.home + self.term.clear + self.term.move_y(int(h * 0.10)))
            for component in title_split:  # Prints centered title
                component = (
                    str(component)
                    + " " * (max_chars - len(component))
                    + "  " * int(w * 0.03)
                )
                print(self.term.center(component))
            print(self.term.move_down(3))  # Sets the cursor to the options position
            print_options()
            while (
                pressed := self.term.inkey().name
            ) != "KEY_ENTER":  # Loops till the user chooses an option
                if pressed == "KEY_TAB":
                    select_option()
                    print_options()
        print(self.term.home + self.term.clear)  # Resets the terminal

        if not self.curr_highlight:
            return "NEW_LOBBY"
        elif self.curr_highlight == 1:
            return "CONNECT_TO_LOBBY"
        elif self.curr_highlight == 2:
            return "SETTINGS"
        else:
            return "EXIT"

    def draw_tile(
        self,
        x: int = 0,
        y: int = 0,
        text: str = None,
        fg: str = "black",
        bg: str = "white",
    ) -> None:
        """Draws one tile and text inside of it."""
        style = getattr(self.term, f"{fg}_on_{bg}")
        for j in range(y, y + self.tile_height):
            for i in range(x, x + self.tile_width):
                with self.term.location(i, j):
                    print(style(" "))
        with self.term.location(x, y + (self.tile_height // 2)):
            print(style(str.center(text, self.tile_width)))

    def get_piece_meta(self, row: int, col: int) -> tuple:
        """Returns color and piece info of the cell."""
        if (row + col) % 2 == 0:
            bg = self.theme.themes[self.colour_scheme]["white_squares"]
        else:
            bg = self.theme.themes[self.colour_scheme]["black_squares"]
        piece_value = self.chess_board[row][col]
        piece, color = mapper[piece_value]
        return (piece, color, bg)

    @staticmethod
    def fen_to_board(fen: str) -> list:
        """Return the chess array representation of FEN."""
        board = []
        fen_parts = fen.split(" ")
        board_str = fen_parts[0]
        for i in board_str.split("/"):
            if len(i) == 8:
                board.append(["em" if _.isnumeric() else _ for _ in i])
            else:
                row = []
                for j in i:
                    if j.isnumeric():
                        row = row + ["em"] * int(j)
                    else:
                        row.append(j)
                board.append(row)
        return board

    def show_game_screen(self) -> None:
        """Shows the chess board."""
        print(self.term.home + self.theme.background + self.term.clear)
        with self.term.hidden_cursor():
            for i in range(len(self)):
                # for every col we need to add number too!
                num = len(self) - i
                x = self.tile_width // 2
                y = i * self.tile_height + self.tile_height // 2
                with self.term.location(x, y):
                    print(num)
                for j in range(len(self)):
                    self.update_block(i, j)
            # adding Alphabets for columns
            for i in range(len(self)):
                with self.term.location(
                    x * 2 - 1 + i * self.tile_width, len(self) * self.tile_height
                ):
                    print(str.center(COL[i], len(self)))

            try:
                self.web_socket.send("BOARD::GET_BOARD")
                no = True
                while no:
                    data = self.web_socket.recv().split("::")
                    self.chess.set_fen(data[2])
                    self.fen = self.chess.give_board()
                    no = False
            except Exception:
                print(data)
                raise
            while True:
                # available_moves = chessboard.all_available_moves()
                # get the latest board
                if self.player.player_id == 1 and not self.is_white_turn():
                    new_board = False
                    while not new_board:
                        data = self.web_socket.recv().split("::")
                        if data[0] == "BOARD" and data[1] == "BOARD":
                            if self.is_white_turn(data[2]):
                                self.chess.set_fen(data[2])
                                self.fen = self.chess.give_board()
                                new_board = True

                if self.player.player_id == 2 and self.is_white_turn():
                    new_board = False
                    while not new_board:
                        data = self.web_socket.recv().split("::")
                        if data[0] == "BOARD" and data[1] == "BOARD":
                            if not self.is_white_turn(data[2]):
                                self.chess.set_fen(data[2])
                                self.fen = self.chess.give_board()
                                new_board = True

                start_move, end_move = self.handle_arrows()
                # print(start_move, end_move)
                with self.term.location(0, self.term.height - 10):
                    move = "".join((*start_move, *end_move)).lower()
                    self.chess.move_piece(move)
                    self.fen = self.chess.give_board()
                    self.chess_board = self.fen_to_board(self.fen)
                self.update_block(
                    len(self) - int(end_move[1]), COL.index(end_move[0].upper())
                )
                self.update_block(
                    len(self) - int(start_move[1]),
                    COL.index(start_move[0].upper()),
                )
                self.moves_played += 1
                if (
                    self.moves_played % self.moves_limit == 0
                    and self.visible_layers > 2
                ):
                    self.visible_layers -= 2
                    invisible_layers = (8 - self.visible_layers) // 2
                    self.hidden_layer[0:invisible_layers, :] = 0
                    self.hidden_layer[-invisible_layers:, :] = 0
                    self.hidden_layer[:, 0:invisible_layers] = 0
                    self.hidden_layer[:, -invisible_layers:] = 0
                    for i in range(8):
                        for j in range(8):
                            self.update_block(i, j)

                # update the server
                self.web_socket.send(f"BOARD::MOVE::{move}")
                try:
                    data = [""]
                    self.web_socket.send("BOARD::GET_BOARD")
                    while data[0] != "BOARD":
                        data = self.web_socket.recv().split("::")
                    self.chess.set_fen(data[2])
                except Exception:
                    print(data)
                    raise

    def update_block(self, row: int, col: int) -> None:
        """Updates block on row and col(we must first mutate actual list first)."""
        piece, color, bg = self.get_piece_meta(row, col)
        if self.selected_row == row and self.selected_col == col:
            bg = self.theme.themes[self.colour_scheme]["selected_square"]
        elif [row, col] in self.possible_moves:
            bg = self.theme.themes[self.colour_scheme]["legal_squares"]
        make_invisible = (
            self.hidden_layer[row][col] == 0
            and not self.chess_board[row][col] in WHITE_PIECES
        )
        if make_invisible:
            piece = " "
        self.draw_tile(
            self.tile_width + col * (self.tile_width + self.offset_x),
            row * (self.tile_height + self.offset_y),
            text=piece,
            fg=color,
            bg=bg,
        )

    @staticmethod
    def get_row_col(row: int, col: str) -> tuple:
        """Returns row and col index."""
        return (8 - int(row), COL.index(col.upper()))

    def get_possible_move(self, piece: str) -> list:
        """Gives possible moves for specific piece."""
        moves = self.chess.all_available_moves()
        piece = piece.lower()
        return [i for i in moves if piece in i]

    def is_white_turn(self, fen: str = None) -> bool:
        """Returns if it's white's turn."""
        if fen:
            fen_parts = fen.split(" ")
        else:
            fen_parts = self.fen.split(" ")
        return fen_parts[1] == "w"

    def highlight_moves(self, move: str) -> None:
        """Take a piece and highlights all possible moves."""
        old_moves = deepcopy(self.possible_moves)
        self.possible_moves = []
        # removes old moves
        for i in old_moves:
            self.update_block(i[0], i[1])
        if not move:
            return
        # highlights the possible moves.
        piece = self.chess_board[self.selected_row][self.selected_col]
        if piece == "em":
            return
        for i in self.get_possible_move("".join(move)):
            x = len(self) - int(i[3])
            y = COL.index(i[2].upper())
            self.possible_moves.append([x, y])
            self.update_block(x, y)
        with self.term.location(0, self.term.height - 5):
            print(self.possible_moves)

    def handle_arrows(self) -> tuple:
        """Manages the arrow movement on board."""
        start_move = end_move = False
        while True:
            with self.term.cbreak():
                inp = self.term.inkey()
            input_key = repr(inp)
            if input_key == "KEY_DOWN":
                if self.selected_row < 7:
                    self.selected_row += 1
                    self.update_block(self.selected_row - 1, self.selected_col)
                    self.update_block(self.selected_row, self.selected_col)
            elif input_key == "KEY_UP":
                if self.selected_row > 0:
                    self.selected_row -= 1
                    self.update_block(self.selected_row + 1, self.selected_col)
                    self.update_block(self.selected_row, self.selected_col)
            elif input_key == "KEY_LEFT":
                if self.selected_col > 0:
                    self.selected_col -= 1
                    self.update_block(self.selected_row, self.selected_col + 1)
                    self.update_block(self.selected_row, self.selected_col)
            elif input_key == "KEY_RIGHT":
                if self.selected_col < 7:
                    self.selected_col += 1
                    self.update_block(self.selected_row, self.selected_col - 1)
                    self.update_block(self.selected_row, self.selected_col)
            elif input_key == "KEY_ENTER":
                move = self.chess_board[self.selected_row][self.selected_col]
                if not start_move:
                    # if clicked empty block
                    if move == "em":
                        continue
                    is_valid = (
                        move in WHITE_PIECES
                        if self.is_white_turn()
                        else move in BLACK_PIECES
                    )
                    if not is_valid:
                        continue
                    start_move = (
                        COL[self.selected_col],
                        ROW[len(self) - self.selected_row - 1],
                    )
                    self.highlight_moves(start_move)
                else:
                    if [self.selected_row, self.selected_col] in self.possible_moves:
                        end_move = (
                            COL[self.selected_col],
                            ROW[len(self) - self.selected_row - 1],
                        )
                        old_moves = deepcopy(self.possible_moves)
                        self.possible_moves = []
                        for i in old_moves:
                            self.update_block(i[0], i[1])
                        return start_move, end_move
                    else:
                        if move == "em":
                            start_move = False
                            end_move = False
                            self.highlight_moves(start_move)
                            continue
                        is_same_color = (
                            move in WHITE_PIECES
                            if self.is_white_turn()
                            else move in BLACK_PIECES
                        )
                        if is_same_color:
                            start_move = (
                                COL[self.selected_col],
                                ROW[len(self) - self.selected_row - 1],
                            )
                            end_move = False
                            self.highlight_moves(start_move)
                            continue
                        start_move = False
                        end_move = False
                        self.highlight_moves(start_move)

    def reset_class(self) -> None:
        """Reset player game room info."""
        self.game_id = None
        self.player.player_id = None

    def start_game(self) -> None:
        """
        Starts the chess game.

        TODO : check for net connection
        TODO: Check if console supported
        """
        if self.show_welcome_screen() == "q":
            print(self.term.clear + self.term.exit_fullscreen)
        else:
            # call show_game_menu

            menu_choice = "NO_EXIT"
            while menu_choice != "EXIT":
                if self.player:
                    self.reset_class()
                menu_choice = self.show_game_menu()
                if menu_choice == "NEW_LOBBY":
                    # make a new lobby
                    print(self.create_lobby())
                    resp = self.connect_to_lobby()
                    if resp != "READY":
                        print(resp)
                elif menu_choice == "CONNECT_TO_LOBBY":
                    # connect to a lobby
                    resp = self.connect_to_lobby()
                    if resp != "READY":
                        print(resp)
                elif menu_choice == "SETTINGS":
                    # open settings menu
                    pass
                print(self.term.home + self.theme.background + self.term.clear)
                if self.player.player_id:
                    try:
                        self.show_game_screen()
                    except Exception as e:
                        print(e)
                        raise
            # exit the game peacefully
            self.web_socket.close()
            print(self.term.clear + self.term.exit_fullscreen + self.term.clear)
