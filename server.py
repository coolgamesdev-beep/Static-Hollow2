import asyncio
import json
import random
import math
import os
from datetime import datetime

# Try aiohttp first (better for Render), fallback to websockets
try:
    from aiohttp import web
    USE_AIOHTTP = True
except ImportError:
    import websockets
    USE_AIOHTTP = False

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
    level = [row[:] for row in LEVELS[0]]
    rooms[room_id] = {
        "players": {},
        "monsters": [Monster(5+i*4, 5+i*3, "stalker") for i in range(3)],
        "state": {"level": 1, "artifacts_found": 0, "total_artifacts": 3, "game_over": False},
        "level_data": level,
        "password": password,
        "created_at": datetime.now()
    }
    return rooms[room_id]

async def handle_ws_message(ws, data, player_id, room_id):
    """Handle a single WebSocket message"""
    msg_type = data.get('type')

    if msg_type == 'create_room':
        new_room_id = data.get('room_id', f"room_{random.randint(1000,9999)}")
        password = data.get('password', '')

        if new_room_id in rooms:
            await ws.send_str(json.dumps({
                "type": "error",
                "message": "Room already exists"
            }))
            return None, None

        room = create_room(new_room_id, password)

        await ws.send_str(json.dumps({
            "type": "room_created",
            "room_id": new_room_id,
            "has_password": bool(password)
        }))
        return None, None

    elif msg_type == 'join':
        requested_room = data.get('room', 'default')
        password = data.get('password', '')
        player_id = data.get('player_id', f"player_{random.randint(1000,9999)}")
        room_id = requested_room

        if room_id not in rooms:
            await ws.send_str(json.dumps({
                "type": "error",
                "message": "Room not found"
            }))
            return player_id, None

        room = rooms[room_id]
        if room["password"] and room["password"] != password:
            await ws.send_str(json.dumps({
                "type": "error",
                "message": "Wrong password"
            }))
            return player_id, None

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
            "websocket": ws,
            "name": data.get('name', 'Unknown')
        }

        await ws.send_str(json.dumps({
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

        return player_id, room_id

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

    elif msg_type in ('webrtc_offer', 'webrtc_answer', 'ice_candidate'):
        target = data.get('target')
        if room_id in rooms and target in rooms[room_id]["players"]:
            target_ws = rooms[room_id]["players"][target].get('websocket')
            if target_ws:
                await target_ws.send_str(json.dumps({
                    **data,
                    "from": player_id
                }))

    elif msg_type == 'chat':
            if room_id in rooms and player_id in rooms[room_id]["players"]:
                await broadcast(room_id, {
                    "type": "chat",
                    "from_name": rooms[room_id]["players"][player_id].get('name', 'Unknown'),
                    "message": data.get('message', ''),
                    "player_id": player_id
                })

        elif msg_type == 'voice_request':
        target = data.get('target')
        if room_id in rooms and target in rooms[room_id]["players"]:
            target_ws = rooms[room_id]["players"][target].get('websocket')
            if target_ws:
                await target_ws.send_str(json.dumps({
                    "type": "voice_request",
                    "from": player_id,
                    "from_name": rooms[room_id]["players"][player_id].get('name', 'Unknown')
                }))

    return player_id, room_id

async def broadcast(room_id, message, exclude=None):
    if room_id not in rooms:
        return
    for pid, player in rooms[room_id]["players"].items():
        if pid != exclude and 'websocket' in player:
            try:
                await player['websocket'].send_str(json.dumps(message))
            except:
                pass

async def game_loop():
    while True:
        await asyncio.sleep(0.025)  # 40 FPS
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

# ==================== AIOHTTP VERSION (for Render) ====================
if USE_AIOHTTP:
    async def websocket_handler(request):
        """Handle WebSocket connections via aiohttp"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        player_id = None
        room_id = None

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    player_id, room_id = await handle_ws_message(ws, data, player_id, room_id)
                elif msg.type == web.WSMsgType.ERROR:
                    print(f'WebSocket error: {ws.exception()}')
        finally:
            if room_id in rooms and player_id in rooms[room_id]["players"]:
                del rooms[room_id]["players"][player_id]
                await broadcast(room_id, {
                    "type": "player_left",
                    "player_id": player_id
                })
                if len(rooms[room_id]["players"]) == 0:
                    del rooms[room_id]

        return ws

    async def health_handler(request):
        """HTTP health check for Render - aiohttp handles HEAD automatically with GET"""
        total_players = sum(len(r["players"]) for r in rooms.values())
        return web.json_response({
            "status": "alive",
            "players": total_players,
            "rooms": len(rooms)
        })

    async def main_aiohttp():
        app = web.Application()
        app.router.add_get('/ws', websocket_handler)
        app.router.add_get('/health', health_handler)  # HEAD is auto-handled by aiohttp

        runner = web.AppRunner(app)
        await runner.setup()

        port = int(os.environ.get('PORT', 8765))
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()

        print(f"AioHTTP server started on port {port}")
        print(f"WebSocket: ws://0.0.0.0:{port}/ws")
        print(f"Health: http://0.0.0.0:{port}/health")

        await game_loop()

# ==================== WEBSOCKETS VERSION (fallback) ====================
else:
    import websockets

    async def handle_client(websocket):
        """WebSocket handler for websockets library"""
        player_id = None
        room_id = None

        try:
            async for message in websocket:
                data = json.loads(message)
                player_id, room_id = await handle_ws_message(websocket, data, player_id, room_id)
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

    async def main_websockets():
        async with websockets.serve(handle_client, "0.0.0.0", 8765):
            print("WebSockets server started on ws://0.0.0.0:8765")
            await game_loop()

# ==================== MAIN ====================

async def main():
    if USE_AIOHTTP:
        await main_aiohttp()
    else:
        await main_websockets()

if __name__ == "__main__":
    asyncio.run(main())
