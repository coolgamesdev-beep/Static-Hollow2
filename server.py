import asyncio
import websockets
import json
import random
import math
import hashlib
from datetime import datetime

# Game state
rooms = {}

# Pixel art level data (0=floor, 1=wall, 2=artifact, 3=exit, 4=spawn)
LEVELS = [
    [
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [1,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,4,0,1,0,0,0,0,0,1,0,0,0,2,0,0,0,0,1],
        [1,0,0,0,1,0,0,1,1,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,1,0,0,0,0,0,1,1,1,0,0,0,1],
        [1,1,1,0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,1,0,0,1,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,0,1,1,1,1,0,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,1,0,0,0,0,0,1,0,0,1,1,1,1,0,0,1],
        [1,0,2,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,1,0,0,1,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,1,1,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,2,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,1],
        [1,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,3,1],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]
    ]
]

class Monster:
    def __init__(self, x, y, monster_type="stalker"):
        self.x = x
        self.y = y
        self.type = monster_type
        self.speed = 0.03
        self.target = None
        self.state = "idle"
        self.patrol_points = [(x, y), (x+3, y), (x+3, y+3), (x, y+3)]
        self.patrol_idx = 0
        self.detection_range = 5
        self.last_update = datetime.now()

    def update(self, players_list, level_data):
        now = datetime.now()
        if (now - self.last_update).total_seconds() < 0.1:
            return
        self.last_update = now

        nearest = None
        min_dist = float('inf')
        for p in players_list:
            dx = p['x'] - self.x
            dy = p['y'] - self.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < min_dist:
                min_dist = dist
                nearest = p

        if nearest and min_dist < self.detection_range:
            self.state = "chase"
            self.target = nearest
        else:
            self.state = "patrol"
            self.target = None

        if self.state == "chase" and self.target:
            dx = self.target['x'] - self.x
            dy = self.target['y'] - self.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 0:
                self.x += (dx/dist) * self.speed
                self.y += (dy/dist) * self.speed
        else:
            tx, ty = self.patrol_points[self.patrol_idx]
            dx = tx - self.x
            dy = ty - self.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < 0.2:
                self.patrol_idx = (self.patrol_idx + 1) % len(self.patrol_points)
            else:
                self.x += (dx/dist) * (self.speed * 0.5)
                self.y += (dy/dist) * (self.speed * 0.5)

        grid_x = int(self.x)
        grid_y = int(self.y)
        if 0 <= grid_y < len(level_data) and 0 <= grid_x < len(level_data[0]):
            if level_data[grid_y][grid_x] == 1:
                self.x -= (dx/dist) * self.speed if dist > 0 else 0
                self.y -= (dy/dist) * self.speed if dist > 0 else 0

def create_room(room_id, password=""):
    level = [row[:] for row in LEVELS[0]]  # Deep copy
    rooms[room_id] = {
        "players": {},
        "monsters": [Monster(5+i*4, 5+i*3, "stalker") for i in range(3)],
        "state": {"level": 1, "artifacts_found": 0, "total_artifacts": 3, "game_over": False},
        "level_data": level,
        "password": password,
        "created_at": datetime.now()
    }
    return rooms[room_id]

async def handle_client(websocket):
    player_id = None
    room_id = None

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get('type')

            if msg_type == 'create_room':
                new_room_id = data.get('room_id', f"room_{random.randint(1000,9999)}")
                password = data.get('password', '')

                if new_room_id in rooms:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Room already exists"
                    }))
                    continue

                room = create_room(new_room_id, password)

                await websocket.send(json.dumps({
                    "type": "room_created",
                    "room_id": new_room_id,
                    "has_password": bool(password)
                }))

            elif msg_type == 'join':
                requested_room = data.get('room', 'default')
                password = data.get('password', '')
                player_id = data.get('player_id', f"player_{random.randint(1000,9999)}")
                room_id = requested_room

                if room_id not in rooms:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Room not found"
                    }))
                    continue

                room = rooms[room_id]
                if room["password"] and room["password"] != password:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Wrong password"
                    }))
                    continue

                # Find spawn point
                spawn_x, spawn_y = 2.5, 2.5
                for y, row in enumerate(room["level_data"]):
                    for x, cell in enumerate(row):
                        if cell == 4:
                            spawn_x, spawn_y = x + 0.5, y + 0.5
                            break

                room["players"][player_id] = {
                    "id": player_id,
                    "x": spawn_x,
                    "y": spawn_y,
                    "vx": 0,
                    "vy": 0,
                    "dir": "down",
                    "frame": 0,
                    "health": 100,
                    "flashlight": True,
                    "artifacts": 0,
                    "websocket": websocket,
                    "name": data.get('name', 'Unknown')
                }

                await websocket.send(json.dumps({
                    "type": "init",
                    "player_id": player_id,
                    "level": room["level_data"],
                    "players": {k: {kk: vv for kk, vv in v.items() if kk != 'websocket'} 
                               for k, v in room["players"].items()}
                }))

                await broadcast(room_id, {
                    "type": "player_joined",
                    "player": {k: v for k, v in room["players"][player_id].items() if k != 'websocket'}
                }, exclude=player_id)

            elif msg_type == 'move':
                if room_id in rooms and player_id in rooms[room_id]["players"]:
                    p = rooms[room_id]["players"][player_id]
                    p['x'] = data.get('x', p['x'])
                    p['y'] = data.get('y', p['y'])
                    p['vx'] = data.get('vx', 0)
                    p['vy'] = data.get('vy', 0)
                    p['dir'] = data.get('dir', p['dir'])
                    p['frame'] = data.get('frame', p['frame'])

                    level = rooms[room_id]["level_data"]
                    gx, gy = int(p['x']), int(p['y'])
                    if 0 <= gy < len(level) and 0 <= gx < len(level[0]):
                        if level[gy][gx] == 2:
                            level[gy][gx] = 0
                            p['artifacts'] += 1
                            rooms[room_id]["state"]["artifacts_found"] += 1
                            await broadcast(room_id, {
                                "type": "artifact_collected",
                                "player_id": player_id,
                                "x": gx,
                                "y": gy,
                                "total": rooms[room_id]["state"]["artifacts_found"]
                            })

                            if rooms[room_id]["state"]["artifacts_found"] >= rooms[room_id]["state"]["total_artifacts"]:
                                await broadcast(room_id, {
                                    "type": "game_win",
                                    "message": "All artifacts found! Escape through the exit!"
                                })

                    if level[gy][gx] == 3 and rooms[room_id]["state"]["artifacts_found"] >= rooms[room_id]["state"]["total_artifacts"]:
                        await broadcast(room_id, {"type": "level_complete"})

                    await broadcast(room_id, {
                        "type": "player_update",
                        "player": {k: v for k, v in p.items() if k != 'websocket'}
                    }, exclude=player_id)

            elif msg_type == 'webrtc_offer' or msg_type == 'webrtc_answer' or msg_type == 'ice_candidate':
                target = data.get('target')
                if room_id in rooms and target in rooms[room_id]["players"]:
                    target_ws = rooms[room_id]["players"][target].get('websocket')
                    if target_ws:
                        await target_ws.send(json.dumps({
                            **data,
                            "from": player_id
                        }))

            elif msg_type == 'voice_request':
                target = data.get('target')
                if room_id in rooms and target in rooms[room_id]["players"]:
                    target_ws = rooms[room_id]["players"][target].get('websocket')
                    if target_ws:
                        await target_ws.send(json.dumps({
                            "type": "voice_request",
                            "from": player_id,
                            "from_name": rooms[room_id]["players"][player_id].get('name', 'Unknown')
                        }))

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if room_id in rooms and player_id in rooms[room_id]["players"]:
            del rooms[room_id]["players"][player_id]
            await broadcast(room_id, {
                "type": "player_left",
                "player_id": player_id
            })
            if len(rooms[room_id]["players"]) == 0:
                del rooms[room_id]

async def broadcast(room_id, message, exclude=None):
    if room_id not in rooms:
        return
    for pid, player in rooms[room_id]["players"].items():
        if pid != exclude and 'websocket' in player:
            try:
                await player['websocket'].send(json.dumps(message))
            except:
                pass

async def game_loop():
    while True:
        await asyncio.sleep(0.05)
        for room_id, room in list(rooms.items()):
            players_list = [{k: v for k, v in p.items() if k != 'websocket'} 
                          for p in room["players"].values()]

            for monster in room["monsters"]:
                monster.update(players_list, room["level_data"])

            for pid, player in room["players"].items():
                for monster in room["monsters"]:
                    dx = player['x'] - monster.x
                    dy = player['y'] - monster.y
                    dist = math.sqrt(dx*dx + dy*dy)
                    if dist < 0.5:
                        player['health'] -= 2
                        if player['health'] <= 0:
                            await broadcast(room_id, {
                                "type": "player_died",
                                "player_id": pid
                            })
                            player['health'] = 100
                            player['x'] = 2.5
                            player['y'] = 2.5

            await broadcast(room_id, {
                "type": "monsters_update",
                "monsters": [{"x": m.x, "y": m.y, "type": m.type, "state": m.state} for m in room["monsters"]]
            })

            for pid, player in room["players"].items():
                await broadcast(room_id, {
                    "type": "health_update",
                    "player_id": pid,
                    "health": player['health']
                })

async def main():
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        print("Server started on ws://0.0.0.0:8765")
        print("Players can now create/join rooms!")
        await game_loop()

if __name__ == "__main__":
    asyncio.run(main())
