from pynput.keyboard import Key, Events, KeyCode
import subprocess
import json
import time
import sys

# Variables

rooms = {}
objects = {}       # objects[room_id] - static definitions from objects.json
obj_states = {}    # obj_states[room_id][i] = {"position": [x, y], "health": int|None}
player = None
current_room_id = 0
grid = None
warning = ""
entry_move_counter = 0

PROJECTILE_DAMAGE = 25
ARROW_DIRECTIONS = {
    Key.up: (0, -1),
    Key.down: (0, 1),
    Key.left: (-1, 0),
    Key.right: (1, 0),
}

# Classes

class Player:
    class _Position:
        def __init__(self, x=0, y=0):
            self.x = x
            self.y = y

        def __iter__(self):
            return iter((self.x, self.y))

    def __init__(self, name, icon, x=0, y=0):
        self.name = name
        self.icon = icon
        self.health = 100
        self.facing = (1, 0)  # default facing right
        self._position = Player._Position(x, y)

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position.x, self._position.y = value

# Generic Functions

def get_direction(key):
    if key == KeyCode.from_char("w"):
        return (0, -1)
    elif key == KeyCode.from_char("s"):
        return (0, 1)
    elif key == KeyCode.from_char("a"):
        return (-1, 0)
    elif key == KeyCode.from_char("d"):
        return (1, 0)
    return None

def handle_key(key):
    if key == Key.esc:
        return False

    if key in ARROW_DIRECTIONS:
        player.facing = ARROW_DIRECTIONS[key]
    elif get_direction(key) is not None:
        try_move_player(*get_direction(key))
    elif key == Key.space:
        fire_projectile()

    return True

# Room Logic

def load_rooms():
    with open("rooms.json") as f:
        data = json.load(f)
    return {int(k): v for k, v in data.items()}

def load_objects():
    with open("objects.json") as f:
        data = json.load(f)
    return {int(k): v for k, v in data.items()}

def enter_room(room_id, spawn_pos=(0, 0)):
    global current_room_id, grid, warning, entry_move_counter
    if room_id == 99:
        game_win()
        return
    warning = f"Now entering: {rooms[room_id]['name']}"
    entry_move_counter = 3
    player.position = spawn_pos
    if room_id not in obj_states:
        obj_states[room_id] = [
            {"position": list(obj["position"]), "health": obj.get("health")}
            for obj in objects[room_id]
        ]
    current_room_id = room_id
    grid = build_grid(rooms[room_id])

# Grid Logic

def build_grid(room):
    grid_width = room["width"] + 2
    grid_height = room["height"] + 2
    result = []
    for x in range(grid_width):
        col = []
        for y in range(grid_height):
            if x == 0 or x == grid_width - 1 or y == 0 or y == grid_height - 1:
                col.append("⬜")
            else:
                col.append("  ")
        result.append(col)
    return result

def render_board(projectile_pos=None):
    subprocess.run(["clear"])
    display = [col[:] for col in grid]
    room_objs = objects[current_room_id]
    states = obj_states[current_room_id]

    # Draw non-movables first so movables appear on top when stacked on a portal
    for i, obj in enumerate(room_objs):
        if not obj["movable"]:
            ox, oy = states[i]["position"]
            display[ox + 1][oy + 1] = obj["icon"]

    for i, obj in enumerate(room_objs):
        if obj["movable"]:
            ox, oy = states[i]["position"]
            display[ox + 1][oy + 1] = obj["icon"]

    if projectile_pos is not None:
        px, py = projectile_pos
        display[px + 1][py + 1] = "🍅"

    display[player.position.x + 1][player.position.y + 1] = player.icon

    for y in range(len(grid[0])):
        print("".join(display[x][y] for x in range(len(grid))))

    facing_emoji = {(0, -1): "⬆️", (0, 1): "⬇️", (-1, 0): "⬅️", (1, 0): "➡️"}.get(player.facing, "➡️")
    filled = round(player.health / 100 * 20)
    bar = "█" * filled + "░" * (20 - filled)
    print()
    print(f"⚠️ {warning}" if warning else "")
    print(f"❤️ [{bar}] {player.health}/100 | {facing_emoji} Aim")
    print()

    adjacent, adj_index = get_adjacent_object()
    if adjacent is not None and entry_move_counter == 0:
        print(f"📌 {adjacent['name']} - {adjacent['description']}")
        adj_health = obj_states[current_room_id][adj_index]["health"]
        if adj_health is not None:
            adj_max = adjacent["health"]
            adj_filled = round(adj_health / adj_max * 20)
            adj_bar = "█" * adj_filled + "░" * (20 - adj_filled)
            print(f"💀 [{adj_bar}] {adj_health}/{adj_max}")
        else:
            print()
    else:
        print()
        print()

    print()
    print("WASD to Move | Space to Fire | ESC to Quit")

# Object Logic

def find_objects_at(states, x, y):
    return [i for i, s in enumerate(states) if s["position"][0] == x and s["position"][1] == y]

def damage_object(room_id, obj_index):
    if obj_states[room_id][obj_index]["health"] is None:
        return
    obj_states[room_id][obj_index]["health"] -= PROJECTILE_DAMAGE
    if obj_states[room_id][obj_index]["health"] <= 0:
        objects[room_id].pop(obj_index)
        obj_states[room_id].pop(obj_index)

def get_adjacent_object():
    px, py = player.position.x, player.position.y
    states = obj_states[current_room_id]
    for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
        i = next((i for i, s in enumerate(states) if s["position"][0] == px + dx and s["position"][1] == py + dy), None)
        if i is not None:
            return objects[current_room_id][i], i
    return None, None

def categorize_objects_at(x, y):
    """Returns (portal_index, movable_index, blocker_index, hazard_index) for objects at (x, y)."""
    room_objs = objects[current_room_id]
    states = obj_states[current_room_id]
    indices = find_objects_at(states, x, y)

    portal = next((i for i in indices if not room_objs[i]["movable"] and room_objs[i]["room_on_overlap"] != -1), None)
    movable = next((i for i in indices if room_objs[i]["movable"]), None)
    hazard = next((i for i in indices if "damage" in room_objs[i]), None)
    blocker = next((i for i in indices if not room_objs[i]["movable"]
                    and room_objs[i]["room_on_overlap"] == -1
                    and "damage" not in room_objs[i]), None)

    return portal, movable, blocker, hazard

def try_push_object(obj_index, dx, dy):
    states = obj_states[current_room_id]
    room_objs = objects[current_room_id]
    pos = states[obj_index]["position"]
    push_x = pos[0] + dx
    push_y = pos[1] + dy

    if grid[push_x + 1][push_y + 1] == "⬜":
        return False

    for i in find_objects_at(states, push_x, push_y):
        obj_at = room_objs[i]
        if not obj_at["movable"] and "damage" not in obj_at:
            return False  # portals and solid blockers block push; hazards don't

    states[obj_index]["position"] = [push_x, push_y]
    return True

# Player Logic

def _decrement_entry_counter():
    global entry_move_counter, warning
    if entry_move_counter > 0:
        entry_move_counter -= 1
        if entry_move_counter == 0:
            warning = ""

def try_move_player(dx, dy):
    new_x = player.position.x + dx
    new_y = player.position.y + dy

    if grid[new_x + 1][new_y + 1] == "⬜":
        return

    portal_index, movable_index, blocker_index, hazard_index = categorize_objects_at(new_x, new_y)

    if blocker_index is not None:
        return

    if portal_index is not None:
        # Portal takes priority - transition even if a movable is also here
        portal = objects[current_room_id][portal_index]
        entry_point = portal["entry_point"]
        enter_room(portal["room_on_overlap"], spawn_pos=tuple(entry_point))
        return

    if movable_index is not None:
        if try_push_object(movable_index, dx, dy):
            player.position = (new_x, new_y)
            _decrement_entry_counter()
        return

    player.position = (new_x, new_y)
    _decrement_entry_counter()

    if hazard_index is not None:
        player.health -= objects[current_room_id][hazard_index]["damage"]

# Projectile Logic

def fire_projectile():
    global warning
    warning = ""
    dx, dy = player.facing
    x = player.position.x
    y = player.position.y

    while True:
        x += dx
        y += dy

        if grid[x + 1][y + 1] == "⬜":
            break

        render_board(projectile_pos=(x, y))
        time.sleep(0.05)

        states = obj_states[current_room_id]
        room_objs = objects[current_room_id]
        hit_indices = find_objects_at(states, x, y)
        if not hit_indices:
            continue

        movable_hit = next((i for i in hit_indices if room_objs[i]["movable"]), None)
        non_movable_hit = next((i for i in hit_indices
                                if not room_objs[i]["movable"] and "damage" not in room_objs[i]), None)

        if movable_hit is not None:
            try_push_object(movable_hit, dx, dy)
            if obj_states[current_room_id][movable_hit]["health"] is None:
                warning = f"{room_objs[movable_hit]['name']} can't be destroyed."
            else:
                damage_object(current_room_id, movable_hit)
            break

        if non_movable_hit is not None:
            if obj_states[current_room_id][non_movable_hit]["health"] is None:
                warning = f"{room_objs[non_movable_hit]['name']} can't be moved or destroyed."
            else:
                damage_object(current_room_id, non_movable_hit)
            break

# End States

def game_over():
    subprocess.run(["clear"])
    subprocess.run(["stty", "echo"])
    print("You died. The facility consumed you.")
    print("Thanks for playing!")
    sys.exit(0)

def game_win():
    subprocess.run(["clear"])
    subprocess.run(["stty", "echo"])
    print("You reached the surface. Dr. Cosor escaped.")
    print("Thanks for playing!")
    sys.exit(0)

# Main Game Loop

def main():
    global rooms, objects, player

    rooms = load_rooms()
    objects = load_objects()
    player = Player(name="", icon="😀")

    enter_room(0)
    subprocess.run(["stty", "-echo"])
    render_board()

    with Events() as events:
        for event in events:
            if not isinstance(event, Events.Press):
                continue

            if not handle_key(event.key):
                subprocess.run(["clear"])
                subprocess.run(["stty", "echo"])
                print("Thanks for playing!")
                break

            if player.health <= 0:
                game_over()
                break

            if event.key == Key.space:
                while events.get(timeout=0) is not None:
                    pass

            render_board()

if __name__ == "__main__":
    main()