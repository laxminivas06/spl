import os
import io
import pandas as pd
import openpyxl
from datetime import datetime
import database

COLUMN_MAPPING = {
    "name": ["name", "player name", "player_name", "fullname", "full name"],
    "roll_no": ["roll no", "roll number", "roll_no", "rollno", "reg no", "id"],
    "year": ["year", "academic year", "class", "batch"],
    "role": ["role", "player role", "type", "specialization", "category"],
    "base_price": ["base price", "base_price", "baseprice", "price", "base"],
    "matches": ["matches", "match", "played", "m"],
    "runs": ["runs", "total runs", "r"],
    "strike_rate": ["strike rate", "strikerate", "strike_rate", "sr", "s/r"],
    "fifties": ["50s", "50", "fifties", "half centuries"],
    "hundreds": ["100s", "100", "hundreds", "centuries"],
    "fours": ["4s", "4", "fours"],
    "sixes": ["6s", "6", "sixes"],
    "wickets": ["wickets", "wkts", "w", "total wickets"],
    "economy": ["economy", "econ", "eco"],
    "catches": ["catches", "catch", "c"],
    "runouts": ["runouts", "run outs", "ro", "runout"]
}

VALID_ROLES = ["Batsman", "Bowler", "All-Rounder", "Wicket Keeper"]

def normalize_role(role_raw):
    if not role_raw:
        return "All-Rounder"
    r = str(role_raw).strip().lower()
    if "bat" in r:
        return "Batsman"
    if "bowl" in r:
        return "Bowler"
    if "keep" in r or "wk" in r:
        return "Wicket Keeper"
    if "all" in r or "round" in r:
        return "All-Rounder"
    return "All-Rounder"

def find_matched_col(df_columns, candidate_names):
    for col in df_columns:
        clean_col = str(col).strip().lower()
        for cand in candidate_names:
            if clean_col == cand:
                return col
    return None

class ExcelService:
    @staticmethod
    def generate_sample_excel_buffer():
        sample_data = [
            {
                "Name": "Rohit Sharma",
                "Roll No": "SPL-2024-101",
                "Year": "4th Year",
                "Role": "Batsman",
                "Base Price": 25000,
                "Matches": 18,
                "Runs": 650,
                "Strike Rate": 152.4,
                "50s": 5,
                "100s": 1,
                "4s": 62,
                "6s": 35,
                "Wickets": 1,
                "Economy": 8.2,
                "Catches": 9,
                "Runouts": 2
            },
            {
                "Name": "Jasprit Bumrah",
                "Roll No": "SPL-2024-102",
                "Year": "3rd Year",
                "Role": "Bowler",
                "Base Price": 25000,
                "Matches": 16,
                "Runs": 30,
                "Strike Rate": 80.0,
                "50s": 0,
                "100s": 0,
                "4s": 2,
                "6s": 1,
                "Wickets": 28,
                "Economy": 5.9,
                "Catches": 6,
                "Runouts": 1
            },
            {
                "Name": "Hardik Pandya",
                "Roll No": "SPL-2024-103",
                "Year": "4th Year",
                "Role": "All-Rounder",
                "Base Price": 30000,
                "Matches": 17,
                "Runs": 410,
                "Strike Rate": 165.0,
                "50s": 3,
                "100s": 0,
                "4s": 34,
                "6s": 26,
                "Wickets": 16,
                "Economy": 7.8,
                "Catches": 11,
                "Runouts": 3
            },
            {
                "Name": "Rishabh Pant",
                "Roll No": "SPL-2024-104",
                "Year": "2nd Year",
                "Role": "Wicket Keeper",
                "Base Price": 20000,
                "Matches": 15,
                "Runs": 480,
                "Strike Rate": 145.2,
                "50s": 4,
                "100s": 0,
                "4s": 45,
                "6s": 22,
                "Wickets": 0,
                "Economy": 0.0,
                "Catches": 16,
                "Runouts": 4
            }
        ]
        df = pd.DataFrame(sample_data)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Players')
        buffer.seek(0)
        return buffer

    @staticmethod
    def import_players_from_file(file_storage):
        filename = file_storage.filename.lower()
        try:
            if filename.endswith('.csv'):
                df = pd.read_csv(file_storage)
            elif filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_storage)
            else:
                return {
                    "success": False,
                    "message": "Invalid file format. Please upload an Excel (.xlsx, .xls) or CSV file."
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error parsing uploaded file: {str(e)}"
            }

        if df.empty:
            return {"success": False, "message": "Uploaded file contains no data rows."}

        # Auto-map columns
        matched_map = {}
        for key, candidates in COLUMN_MAPPING.items():
            col = find_matched_col(df.columns, candidates)
            if col:
                matched_map[key] = col

        if "name" not in matched_map:
            return {
                "success": False,
                "message": f"Required column 'Name' not found. Detected columns: {list(df.columns)}"
            }

        existing_players = database.get_players()
        players_by_roll = {p.get("roll_no", "").strip().lower(): p for p in existing_players if p.get("roll_no")}
        players_by_name = {p["name"].strip().lower(): p for p in existing_players}

        success_count = 0
        updated_count = 0
        failed_rows = []

        def get_val(row, key, default=0, is_float=False):
            if key in matched_map:
                val = row[matched_map[key]]
                if pd.isna(val):
                    return default
                try:
                    return float(val) if is_float else int(float(val))
                except (ValueError, TypeError):
                    return default
            return default

        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-indexed header + 1
            name_val = row[matched_map["name"]]
            if pd.isna(name_val) or not str(name_val).strip():
                failed_rows.append({"row": row_num, "error": "Empty or missing player name"})
                continue

            name = str(name_val).strip()
            roll_no = str(row[matched_map["roll_no"]]).strip() if "roll_no" in matched_map and not pd.isna(row[matched_map["roll_no"]]) else f"SPL-{int(datetime.now().timestamp())}-{row_num}"
            year = str(row[matched_map["year"]]).strip() if "year" in matched_map and not pd.isna(row[matched_map["year"]]) else "1st Year"
            role_raw = row[matched_map["role"]] if "role" in matched_map and not pd.isna(row[matched_map["role"]]) else "All-Rounder"
            role = normalize_role(role_raw)

            base_price = get_val(row, "base_price", default=10000)
            if base_price < 1000:
                base_price = 10000

            batting_stats = {
                "matches": get_val(row, "matches", 0),
                "runs": get_val(row, "runs", 0),
                "strike_rate": get_val(row, "strike_rate", 0.0, is_float=True),
                "fifties": get_val(row, "fifties", 0),
                "hundreds": get_val(row, "hundreds", 0),
                "fours": get_val(row, "fours", 0),
                "sixes": get_val(row, "sixes", 0)
            }
            bowling_stats = {
                "wickets": get_val(row, "wickets", 0),
                "economy": get_val(row, "economy", 0.0, is_float=True)
            }
            fielding_stats = {
                "catches": get_val(row, "catches", 0),
                "runouts": get_val(row, "runouts", 0)
            }

            # Check if updating existing player or creating new
            existing = players_by_roll.get(roll_no.lower()) or players_by_name.get(name.lower())
            
            if existing:
                # Do not overwrite if already sold in live auction
                if existing.get("status") == "SOLD":
                    failed_rows.append({"row": row_num, "error": f"Player '{name}' is already SOLD in auction. Skipped update."})
                    continue

                existing["name"] = name
                existing["roll_no"] = roll_no
                existing["year"] = year
                existing["role"] = role
                existing["base_price"] = base_price
                existing["batting"] = batting_stats
                existing["bowling"] = bowling_stats
                existing["fielding"] = fielding_stats
                updated_count += 1
            else:
                new_player = {
                    "id": f"ply_{int(datetime.now().timestamp())}_{row_num}",
                    "name": name,
                    "roll_no": roll_no,
                    "year": year,
                    "role": role,
                    "base_price": base_price,
                    "status": "AVAILABLE",
                    "photo": "",
                    "sold_price": 0,
                    "sold_team_id": None,
                    "sold_team_name": None,
                    "batting": batting_stats,
                    "bowling": bowling_stats,
                    "fielding": fielding_stats
                }
                existing_players.append(new_player)
                players_by_roll[roll_no.lower()] = new_player
                players_by_name[name.lower()] = new_player
                success_count += 1

        database.save_players(existing_players)

        return {
            "success": True,
            "total_rows": len(df),
            "added_count": success_count,
            "updated_count": updated_count,
            "failed_count": len(failed_rows),
            "failed_rows": failed_rows,
            "message": f"Processed {len(df)} rows: {success_count} added, {updated_count} updated, {len(failed_rows)} errors."
        }
