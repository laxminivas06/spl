import database

class StatsService:
    @staticmethod
    def get_dashboard_stats():
        players = database.get_players()
        teams = database.get_teams()
        bids = database.get_bids()
        settings = database.get_settings()

        total_players = len(players)
        sold_players = [p for p in players if p.get("status") == "SOLD"]
        unsold_players = [p for p in players if p.get("status") == "UNSOLD"]
        available_players = [p for p in players if p.get("status") in ["AVAILABLE", "PLAYER_SELECTED", "BIDDING"]]

        total_auction_value = sum(p.get("sold_price", 0) for p in sold_players)
        
        highest_sold_player = None
        if sold_players:
            highest_sold_player = max(sold_players, key=lambda x: x.get("sold_price", 0))

        # Highest bid in bids table
        highest_bid_amount = max([b.get("amount", 0) for b in bids], default=0)

        # Team spending breakdown
        total_initial_budget = sum(t.get("initial_budget", 0) for t in teams)
        total_balance_remaining = sum(t.get("balance", 0) for t in teams)
        total_spent_by_teams = sum(t.get("spent", 0) for t in teams)

        team_breakdowns = []
        for t in teams:
            squad_count = len(t.get("squad", []))
            team_spent = t.get("spent", 0)
            avg_price = int(team_spent / squad_count) if squad_count > 0 else 0
            team_breakdowns.append({
                "id": t["id"],
                "name": t["name"],
                "short_name": t.get("short_name", t["name"][:3].upper()),
                "color": t.get("color", "#3b82f6"),
                "logo": t.get("logo", ""),
                "owner": t.get("owner", ""),
                "captain": t.get("captain", ""),
                "initial_budget": t.get("initial_budget", 0),
                "balance": t.get("balance", 0),
                "spent": team_spent,
                "squad_count": squad_count,
                "avg_price": avg_price,
                "squad": t.get("squad", [])
            })

        # Category breakdowns
        categories = {"Batsman": 0, "Bowler": 0, "All-Rounder": 0, "Wicket Keeper": 0}
        sold_categories = {"Batsman": 0, "Bowler": 0, "All-Rounder": 0, "Wicket Keeper": 0}
        for p in players:
            role = p.get("role", "All-Rounder")
            if role in categories:
                categories[role] += 1
            if p.get("status") == "SOLD" and role in sold_categories:
                sold_categories[role] += 1

        return {
            "total_players": total_players,
            "sold_count": len(sold_players),
            "unsold_count": len(unsold_players),
            "available_count": len(available_players),
            "total_auction_value": total_auction_value,
            "highest_sold_player": highest_sold_player,
            "highest_bid_amount": highest_bid_amount,
            "total_initial_budget": total_initial_budget,
            "total_balance_remaining": total_balance_remaining,
            "total_spent_by_teams": total_spent_by_teams,
            "team_breakdowns": team_breakdowns,
            "category_stats": categories,
            "sold_category_stats": sold_categories,
            "currency_symbol": settings.get("currency_symbol", "₹")
        }
