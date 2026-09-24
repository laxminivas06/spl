import time
import json
import random
import queue
import threading
from datetime import datetime, timedelta
import config
import database

class EventManager:
    """
    Thread-safe publisher-subscriber manager for Server-Sent Events (SSE).
    """
    def __init__(self):
        self._listeners = []
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def broadcast(self, event_type, data):
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            dead_queues = []
            for q in self._listeners:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead_queues.append(q)
            for q in dead_queues:
                if q in self._listeners:
                    self._listeners.remove(q)

events = EventManager()

def get_next_increment(amount, settings=None):
    if settings is None:
        settings = database.get_settings()
    
    rules = settings.get("increment_rules", [])
    for rule in rules:
        if rule["from"] <= amount < rule["to"]:
            return rule["increment"]
    return settings.get("default_increment", 2000)

def calculate_next_bid(current_bid, base_price, settings=None):
    if current_bid <= 0:
        return base_price
    inc = get_next_increment(current_bid, settings)
    return current_bid + inc

class AuctionEngine:
    @staticmethod
    def calculate_timer(state):
        """
        Calculates live remaining seconds based on server timestamps.
        """
        duration = state.get("timer_duration", config.DEFAULT_TIMER_SECONDS)
        if state.get("is_timer_paused"):
            return state.get("pause_remaining_seconds", duration)
        
        end_ts = state.get("timer_end_timestamp")
        if not end_ts:
            return state.get("timer_remaining", duration)
        
        now_ts = time.time()
        remaining = max(0, int(end_ts - now_ts))
        return remaining

    @staticmethod
    def get_state(for_team_id=None, is_admin=False, is_public=False):
        state = database.get_auction_state()
        players = database.get_players()
        teams = database.get_teams()
        settings = database.get_settings()
        
        # Calculate dynamic server timer
        state["timer_remaining"] = AuctionEngine.calculate_timer(state)

        active_player = None
        if state.get("active_player_id"):
            active_player = next((p for p in players if p["id"] == state["active_player_id"]), None)
            
        announced_player = None
        if state.get("announced_player_id"):
            announced_player = next((p for p in players if p["id"] == state["announced_player_id"]), None)

        leading_team = None
        if state.get("leading_team_id"):
            lead = next((t for t in teams if t["id"] == state["leading_team_id"]), None)
            if lead:
                leading_team = {
                    "id": lead["id"],
                    "name": lead["name"],
                    "short_name": lead.get("short_name", lead["name"][:3].upper()),
                    "color": lead.get("color", "#3b82f6"),
                    "logo": lead.get("logo", "")
                }
            
        all_bids = database.get_bids()
        current_bids = []
        if state.get("active_player_id"):
            current_bids = [b for b in all_bids if b.get("player_id") == state["active_player_id"]]

        # Build public team cards (Never expose private purse or secret bids on public/other screens)
        teams_status = []
        next_bid_amount = state.get("next_bid", 0)
        max_squad = settings.get("max_squad_size", config.MAX_SQUAD_SIZE)

        for t in teams:
            squad_count = len(t.get("squad", []))
            has_slots = squad_count < max_squad
            has_funds = t["balance"] >= next_bid_amount if next_bid_amount > 0 else True
            can_bid = (
                has_funds and 
                has_slots and 
                (state["status"] in ["BIDDING", "PLAYER_ACTIVATED", "PLAYER_SELECTED"]) and 
                (not state.get("is_timer_paused")) and
                (t["id"] != state.get("leading_team_id"))
            )

            team_info = {
                "id": t["id"],
                "name": t["name"],
                "short_name": t.get("short_name", t["name"][:3].upper()),
                "color": t.get("color", "#3b82f6"),
                "logo": t.get("logo", ""),
                "squad_count": squad_count,
                "max_squad": max_squad,
                "is_leading": t["id"] == state.get("leading_team_id"),
                "can_bid": can_bid
            }

            # Only include private purse for Admin or the authenticated team itself
            if is_admin or (for_team_id and for_team_id == t["id"]):
                team_info["balance"] = t["balance"]
                team_info["spent"] = t.get("spent", 0)
                team_info["initial_budget"] = t.get("initial_budget", config.DEFAULT_PURSE)
                team_info["email"] = t.get("email", "")
                team_info["squad"] = t.get("squad", [])

            teams_status.append(team_info)

        return {
            "state": state,
            "player": active_player,
            "announced_player": announced_player,
            "leading_team": leading_team,
            "teams": teams_status,
            "recent_bids": current_bids[-15:],
            "settings": {
                "league_name": settings.get("league_name", "SPL 2026"),
                "currency_symbol": settings.get("currency_symbol", "₹"),
                "default_budget": settings.get("default_budget", config.DEFAULT_PURSE),
                "max_squad_size": max_squad,
                "base_price": settings.get("base_price", config.DEFAULT_BASE_PRICE),
                "timer_seconds": settings.get("timer_seconds", config.DEFAULT_TIMER_SECONDS),
                "increment_rules": settings.get("increment_rules", [])
            }
        }

    @staticmethod
    def announce_player(player_id, user="Anchor"):
        """
        Anchor announces a physically drawn chit.
        Sets status to PLAYER_ANNOUNCED / PLAYER_SELECTED waiting for Admin activation.
        """
        players = database.get_players()
        player = next((p for p in players if p["id"] == player_id), None)
        if not player:
            return {"success": False, "message": "Player not found"}

        if player.get("status") in ["SOLD"]:
            return {"success": False, "message": f"Player {player['name']} is already SOLD!"}

        state = database.get_auction_state()
        base_price = player.get("base_price", config.DEFAULT_BASE_PRICE)

        state["status"] = "PLAYER_ANNOUNCED"
        state["announced_player_id"] = player["id"]
        state["active_player_id"] = player["id"]
        state["current_bid"] = 0
        state["leading_team_id"] = None
        state["leading_team_name"] = None
        state["next_bid"] = base_price
        state["bid_count"] = 0
        state["is_timer_paused"] = True
        state["pause_remaining_seconds"] = config.DEFAULT_TIMER_SECONDS

        database.save_auction_state(state)
        database.log_audit_event(
            action="PLAYER_ANNOUNCED",
            user=user,
            role="anchor",
            player_name=player["name"],
            details=f"Announced Roll No: {player.get('roll_no', '')}, Base Price: ₹{base_price:,}"
        )

        full_state = AuctionEngine.get_state()
        events.broadcast("STATE_UPDATE", full_state)
        return {"success": True, "player": player, "state": state, "message": f"Player '{player['name']}' announced! Waiting for Admin to activate."}

    @staticmethod
    def activate_player(player_id=None, user="Admin"):
        """
        Admin officially activates the announced player on stage and starts live bidding.
        """
        state = database.get_auction_state()
        target_id = player_id or state.get("announced_player_id") or state.get("active_player_id")
        if not target_id:
            return {"success": False, "message": "No player announced to activate"}

        players = database.get_players()
        player = next((p for p in players if p["id"] == target_id), None)
        if not player:
            return {"success": False, "message": "Player not found"}

        if player.get("status") in ["SOLD"]:
            return {"success": False, "message": f"Player {player['name']} is already SOLD!"}

        settings = database.get_settings()
        duration = settings.get("timer_seconds", config.DEFAULT_TIMER_SECONDS)
        base_price = player.get("base_price", config.DEFAULT_BASE_PRICE)

        state["status"] = "BIDDING"
        state["active_player_id"] = player["id"]
        state["announced_player_id"] = player["id"]
        state["current_bid"] = 0
        state["leading_team_id"] = None
        state["leading_team_name"] = None
        state["next_bid"] = base_price
        state["bid_count"] = 0
        state["timer_duration"] = duration
        state["timer_remaining"] = duration
        state["timer_end_timestamp"] = time.time() + duration
        state["is_timer_paused"] = False
        state["pause_remaining_seconds"] = duration

        database.save_auction_state(state)
        database.log_audit_event(
            action="PLAYER_ACTIVATED",
            user=user,
            role="admin",
            player_name=player["name"],
            details=f"Live bidding started with ₹{base_price:,} base price and {duration}s timer."
        )

        full_state = AuctionEngine.get_state()
        events.broadcast("PLAYER_ACTIVATED", full_state)
        return {"success": True, "player": player, "state": state, "message": f"Player '{player['name']}' is now LIVE for bidding!"}

    @staticmethod
    def select_random_player(user="Anchor"):
        """
        Draws a random available player (simulates chit draw).
        """
        players = database.get_players()
        available_players = [p for p in players if p.get("status") in ["AVAILABLE", "UNSOLD_POOL"]]
        if not available_players:
            return {"success": False, "message": "No available players left in the auction pool!"}

        selected = random.choice(available_players)
        return AuctionEngine.announce_player(selected["id"], user=user)

    @staticmethod
    def set_active_player(player_id, user="Admin"):
        """
        Directly sets active player (admin shortcut).
        """
        res = AuctionEngine.announce_player(player_id, user=user)
        if res.get("success"):
            return AuctionEngine.activate_player(player_id, user=user)
        return res

    @staticmethod
    def pause_auction(user="Admin"):
        state = database.get_auction_state()
        if state.get("is_timer_paused"):
            return {"success": True, "message": "Auction is already paused"}

        rem = AuctionEngine.calculate_timer(state)
        state["is_timer_paused"] = True
        state["pause_remaining_seconds"] = rem
        state["status"] = "PAUSED" if state.get("status") == "BIDDING" else state.get("status")

        database.save_auction_state(state)
        database.log_audit_event(action="AUCTION_PAUSED", user=user, role="admin", details=f"Paused with {rem}s remaining.")
        
        full_state = AuctionEngine.get_state()
        events.broadcast("STATE_UPDATE", full_state)
        return {"success": True, "state": state, "message": f"Auction paused ({rem}s remaining)."}

    @staticmethod
    def resume_auction(user="Admin"):
        state = database.get_auction_state()
        if not state.get("is_timer_paused"):
            return {"success": True, "message": "Auction is already running"}

        rem = state.get("pause_remaining_seconds", config.DEFAULT_TIMER_SECONDS)
        if rem <= 0:
            rem = config.DEFAULT_TIMER_SECONDS

        state["is_timer_paused"] = False
        state["timer_end_timestamp"] = time.time() + rem
        state["timer_remaining"] = rem
        if state.get("status") == "PAUSED":
            state["status"] = "BIDDING"

        database.save_auction_state(state)
        database.log_audit_event(action="AUCTION_RESUMED", user=user, role="admin", details=f"Resumed with {rem}s.")
        
        full_state = AuctionEngine.get_state()
        events.broadcast("STATE_UPDATE", full_state)
        return {"success": True, "state": state, "message": f"Auction resumed ({rem}s remaining)."}

    @staticmethod
    def extend_timer(seconds=15, user="Admin"):
        state = database.get_auction_state()
        settings = database.get_settings()
        default_dur = settings.get("timer_seconds", config.DEFAULT_TIMER_SECONDS)

        if state.get("is_timer_paused"):
            current_rem = state.get("pause_remaining_seconds", default_dur)
            state["pause_remaining_seconds"] = current_rem + seconds
            state["timer_remaining"] = state["pause_remaining_seconds"]
        else:
            now = time.time()
            current_end = state.get("timer_end_timestamp") or (now + default_dur)
            new_end = max(now, current_end) + seconds
            state["timer_end_timestamp"] = new_end
            state["timer_remaining"] = max(0, int(new_end - now))

        database.save_auction_state(state)
        database.log_audit_event(action="TIMER_EXTENDED", user=user, role="admin", details=f"Extended by +{seconds}s.")
        
        full_state = AuctionEngine.get_state()
        events.broadcast("STATE_UPDATE", full_state)
        return {"success": True, "state": state, "message": f"Timer extended by +{seconds}s."}

    @staticmethod
    def place_bid(team_id, user_info=None):
        state = database.get_auction_state()
        if state["status"] not in ["BIDDING", "PLAYER_ACTIVATED", "PLAYER_SELECTED"]:
            return {"success": False, "message": f"Cannot bid in status: {state['status']}"}

        if state.get("is_timer_paused"):
            return {"success": False, "message": "Auction is currently PAUSED. Bidding is disabled."}

        if not state.get("active_player_id"):
            return {"success": False, "message": "No active player selected for auction."}

        # Timer expiration check
        rem_seconds = AuctionEngine.calculate_timer(state)
        if rem_seconds <= 0 and state["status"] == "BIDDING":
            return {"success": False, "message": "Timer expired! Bidding is closed for this player."}

        teams = database.get_teams()
        team = next((t for t in teams if t["id"] == team_id), None)
        if not team:
            return {"success": False, "message": "Franchise team not found."}

        if team_id == state.get("leading_team_id"):
            return {"success": False, "message": f"{team['name']} is already holding the highest bid!"}

        settings = database.get_settings()
        max_squad = settings.get("max_squad_size", config.MAX_SQUAD_SIZE)
        if len(team.get("squad", [])) >= max_squad:
            return {"success": False, "message": f"SQUAD LIMIT REACHED! {team['name']} already has {max_squad} players."}

        players = database.get_players()
        player = next((p for p in players if p["id"] == state["active_player_id"]), None)
        if not player:
            return {"success": False, "message": "Active player not found."}

        base_price = player.get("base_price", config.DEFAULT_BASE_PRICE)

        # Determine current bid amount
        if state["current_bid"] == 0:
            bid_amount = base_price
        else:
            bid_amount = state["next_bid"]

        # Validate franchise purse
        if team["balance"] < bid_amount:
            return {
                "success": False,
                "message": f"INSUFFICIENT PURSE! {team['name']} has ₹{team['balance']:,}, but ₹{bid_amount:,} is required.",
                "insufficient_balance": True
            }

        # Calculate next increment
        next_bid = calculate_next_bid(bid_amount, base_price, settings)

        # Record bid
        bid_record = {
            "id": f"bid_{int(datetime.now().timestamp() * 1000)}",
            "player_id": player["id"],
            "player_name": player["name"],
            "team_id": team["id"],
            "team_name": team["name"],
            "amount": bid_amount,
            "timestamp": datetime.now().isoformat(),
            "formatted_time": datetime.now().strftime("%I:%M:%S %p")
        }
        bids = database.get_bids()
        bids.append(bid_record)
        database.save_bids(bids)

        # Reset timer to 25-30s on each valid bid
        bid_timer_dur = min(25, settings.get("timer_seconds", config.DEFAULT_TIMER_SECONDS))
        state["status"] = "BIDDING"
        prev_bid = state.get("current_bid", 0)
        state["current_bid"] = bid_amount
        state["leading_team_id"] = team["id"]
        state["leading_team_name"] = team["name"]
        state["next_bid"] = next_bid
        state["bid_count"] = state.get("bid_count", 0) + 1
        state["timer_end_timestamp"] = time.time() + bid_timer_dur
        state["timer_remaining"] = bid_timer_dur
        state["is_timer_paused"] = False

        database.save_auction_state(state)
        database.log_audit_event(
            action="BID_PLACED",
            user=user_info.get("username") if user_info else team["name"],
            role=user_info.get("role") if user_info else "team",
            player_name=player["name"],
            team_name=team["name"],
            prev_value=prev_bid,
            new_value=bid_amount,
            details=f"Bid placed at ₹{bid_amount:,} (Next: ₹{next_bid:,})"
        )

        full_state = AuctionEngine.get_state()
        events.broadcast("BID_PLACED", {
            "bid": bid_record,
            "state": full_state["state"],
            "leading_team": full_state["leading_team"]
        })

        return {"success": True, "bid": bid_record, "state": state}

    @staticmethod
    def undo_last_bid(user="Admin"):
        state = database.get_auction_state()
        if state["status"] != "BIDDING" or not state.get("active_player_id"):
            return {"success": False, "message": "No active bidding to undo."}

        bids = database.get_bids()
        player_bids = [b for b in bids if b.get("player_id") == state["active_player_id"]]
        if not player_bids:
            return {"success": False, "message": "No bids to undo for this player."}

        last_bid = player_bids[-1]
        bids = [b for b in bids if b["id"] != last_bid["id"]]
        database.save_bids(bids)

        remaining = [b for b in bids if b.get("player_id") == state["active_player_id"]]
        players = database.get_players()
        player = next((p for p in players if p["id"] == state["active_player_id"]), None)
        base_price = player.get("base_price", config.DEFAULT_BASE_PRICE) if player else config.DEFAULT_BASE_PRICE
        settings = database.get_settings()

        if not remaining:
            state["current_bid"] = 0
            state["leading_team_id"] = None
            state["leading_team_name"] = None
            state["next_bid"] = base_price
            state["bid_count"] = 0
        else:
            prev = remaining[-1]
            state["current_bid"] = prev["amount"]
            state["leading_team_id"] = prev["team_id"]
            state["leading_team_name"] = prev["team_name"]
            state["next_bid"] = calculate_next_bid(prev["amount"], base_price, settings)
            state["bid_count"] = len(remaining)

        database.save_auction_state(state)
        database.log_audit_event(
            action="BID_UNDONE",
            user=user,
            role="admin",
            player_name=player["name"] if player else "",
            details=f"Removed bid of ₹{last_bid['amount']:,} by {last_bid['team_name']}"
        )

        full_state = AuctionEngine.get_state()
        events.broadcast("STATE_UPDATE", full_state)
        return {"success": True, "message": "Last bid undone.", "state": state}

    @staticmethod
    def mark_sold(user="Admin"):
        state = database.get_auction_state()
        if state["status"] not in ["BIDDING", "PLAYER_ACTIVATED"] or not state.get("leading_team_id"):
            return {"success": False, "message": "Cannot sell: No valid leading bid has been placed!"}

        player_id = state["active_player_id"]
        winning_team_id = state["leading_team_id"]
        final_price = state["current_bid"]

        players = database.get_players()
        player = next((p for p in players if p["id"] == player_id), None)
        if not player:
            return {"success": False, "message": "Player not found."}

        teams = database.get_teams()
        team = next((t for t in teams if t["id"] == winning_team_id), None)
        if not team:
            return {"success": False, "message": "Winning franchise not found."}

        if team["balance"] < final_price:
            return {"success": False, "message": f"INSUFFICIENT BALANCE! {team['name']} cannot afford winning bid of ₹{final_price:,}."}

        # Atomic transaction: Deduct purse, add to squad, record player sold
        prev_balance = team["balance"]
        team["balance"] -= final_price
        team["spent"] = team.get("spent", 0) + final_price

        squad_player = {
            "id": player["id"],
            "name": player["name"],
            "role": player.get("role", "All-Rounder"),
            "roll_no": player.get("roll_no", ""),
            "year": player.get("year", ""),
            "photo": player.get("photo", ""),
            "bought_for": final_price,
            "sold_at": datetime.now().isoformat(),
            "order": len(team.get("squad", [])) + 1
        }
        if "squad" not in team:
            team["squad"] = []
        team["squad"].append(squad_player)

        player["status"] = "SOLD"
        player["sold_price"] = final_price
        player["sold_team_id"] = team["id"]
        player["sold_team_name"] = team["name"]
        player["sold_at"] = datetime.now().isoformat()

        state["status"] = "SOLD"
        state["is_timer_paused"] = True

        # Atomically write to disk
        database.save_teams(teams)
        database.save_players(players)
        database.save_auction_state(state)

        # Audit logs
        database.log_audit_event(
            action="PLAYER_SOLD",
            user=user,
            role="admin",
            player_name=player["name"],
            team_name=team["name"],
            prev_value=prev_balance,
            new_value=team["balance"],
            details=f"SOLD to {team['name']} for ₹{final_price:,}. Squad size: {len(team['squad'])}"
        )

        full_state = AuctionEngine.get_state()
        events.broadcast("PLAYER_SOLD", {
            "player": player,
            "team": {
                "id": team["id"],
                "name": team["name"],
                "short_name": team.get("short_name", ""),
                "color": team.get("color", "#3b82f6"),
                "logo": team.get("logo", "")
            },
            "price": final_price,
            "state": full_state["state"]
        })

        return {
            "success": True,
            "message": f"SOLD! {player['name']} purchased by {team['name']} for ₹{final_price:,}",
            "player": player,
            "team": team,
            "price": final_price
        }

    @staticmethod
    def mark_unsold(user="Admin"):
        state = database.get_auction_state()
        if state["status"] not in ["PLAYER_SELECTED", "PLAYER_ANNOUNCED", "PLAYER_ACTIVATED", "BIDDING"]:
            return {"success": False, "message": "No active player to mark UNSOLD."}

        player_id = state.get("active_player_id") or state.get("announced_player_id")
        players = database.get_players()
        player = next((p for p in players if p["id"] == player_id), None)
        if not player:
            return {"success": False, "message": "Player not found."}

        player["status"] = "UNSOLD"
        player["unsold_at"] = datetime.now().isoformat()

        state["status"] = "UNSOLD"
        state["current_bid"] = 0
        state["leading_team_id"] = None
        state["leading_team_name"] = None
        state["next_bid"] = 0
        state["is_timer_paused"] = True

        database.save_players(players)
        database.save_auction_state(state)

        database.log_audit_event(
            action="PLAYER_UNSOLD",
            user=user,
            role="admin",
            player_name=player["name"],
            details=f"Marked UNSOLD (Eligible for second chance pool)."
        )

        full_state = AuctionEngine.get_state()
        events.broadcast("PLAYER_UNSOLD", {
            "player": player,
            "state": full_state["state"]
        })

        return {"success": True, "message": f"{player['name']} marked as UNSOLD.", "player": player}

    @staticmethod
    def add_to_second_chance(player_ids, user="Admin"):
        """
        Reactivates selected UNSOLD players into AVAILABLE pool for round 2.
        Sold players cannot be added.
        """
        players = database.get_players()
        count = 0
        for p in players:
            if p["id"] in player_ids and p.get("status") in ["UNSOLD", "UNSOLD_POOL"]:
                p["status"] = "AVAILABLE"
                p["second_chance"] = True
                count += 1

        if count > 0:
            database.save_players(players)
            database.log_audit_event(
                action="SECOND_CHANCE_CREATED",
                user=user,
                role="admin",
                details=f"Reactivated {count} unsold players into second-chance pool."
            )
            full_state = AuctionEngine.get_state()
            events.broadcast("STATE_UPDATE", full_state)

        return {"success": True, "count": count, "message": f"{count} players returned to auction pool for Round 2!"}

    @staticmethod
    def reset_auction_state(user="Admin"):
        state = {
            "status": "READY",
            "active_player_id": None,
            "announced_player_id": None,
            "current_bid": 0,
            "leading_team_id": None,
            "leading_team_name": None,
            "next_bid": 0,
            "bid_count": 0,
            "timer_duration": config.DEFAULT_TIMER_SECONDS,
            "timer_remaining": config.DEFAULT_TIMER_SECONDS,
            "timer_end_timestamp": None,
            "is_timer_paused": False,
            "pause_remaining_seconds": config.DEFAULT_TIMER_SECONDS
        }
        database.save_auction_state(state)
        database.log_audit_event(action="AUCTION_RESET", user=user, role="admin", details="Auction state reset to READY.")
        
        full_state = AuctionEngine.get_state()
        events.broadcast("STATE_UPDATE", full_state)
        return {"success": True, "message": "Auction state reset to READY", "state": state}
