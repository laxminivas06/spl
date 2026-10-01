from datetime import datetime, timedelta
from app.extensions import db
from app.models import Player, PlayerStatus, Franchise, AuctionState, AuctionStatus, Bid, Transaction, SystemSettings
from app.services.audit_service import log_audit

def get_auction_state():
    """Retrieve or create global AuctionState record."""
    state = AuctionState.query.first()
    if not state:
        state = AuctionState(status=AuctionStatus.WAITING)
        db.session.add(state)
        db.session.commit()
    return state

def find_player_by_roll(roll_number):
    """Find available player by roll number for auction preview."""
    if not roll_number:
        raise ValueError("Roll number is required.")

    player = Player.query.filter(Player.roll_number.ilike(str(roll_number).strip())).first()
    if not player:
        raise ValueError(f"PLAYER NOT FOUND. Please verify the announced roll number '{roll_number}'.")

    # Requirement 2: Strict Sold Player Check
    if player.is_sold or str(player.status).upper() == 'SOLD' or player.sold_to is not None:
        raise ValueError(f"Already Sold: Player '{player.name}' (#{player.roll_number}) has already been sold. This player cannot be auctioned again.")

    if player.status == PlayerStatus.UNSOLD:
        raise ValueError(f"PLAYER ALREADY UNSOLD. Player '{player.name}' (#{player.roll_number}) was marked UNSOLD.")

    if player.status != PlayerStatus.AVAILABLE:
        raise ValueError(f"Player '{player.name}' (#{player.roll_number}) is currently {player.status} and cannot be auctioned.")

    state = get_auction_state()
    if state.status not in [AuctionStatus.WAITING, AuctionStatus.SOLD, AuctionStatus.UNSOLD]:
        raise ValueError(f"Cannot select new player while auction is currently active in state '{state.status}'.")

    return player

def activate_player(player_id, admin_id=None):
    """Activate player into PLAYER_PREVIEW state (no bidding yet)."""
    player = Player.query.get(player_id)
    if not player:
        raise ValueError("Player not found.")

    # Requirement 2 & 6: Strict Sold Check
    if player.is_sold or str(player.status).upper() == 'SOLD' or player.sold_to is not None:
        raise ValueError(f"Already Sold: Player '{player.name}' (#{player.roll_number}) has already been sold. This player cannot be auctioned again.")

    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    allowed_statuses = [PlayerStatus.AVAILABLE, PlayerStatus.UNSOLD] if is_sc else [PlayerStatus.AVAILABLE]

    if player.status not in allowed_statuses:
        raise ValueError(f"Player '{player.name}' is currently {player.status} and cannot be activated.")

    state = get_auction_state()
    if state.status not in [AuctionStatus.WAITING, AuctionStatus.SOLD, AuctionStatus.UNSOLD, AuctionStatus.SECOND_CHANCE]:
        raise ValueError("Auction must be in WAITING, SOLD, UNSOLD, or SECOND_CHANCE state to activate a player.")

    state.status = AuctionStatus.PLAYER_PREVIEW
    state.active_player_id = player.id
    state.current_bid = float(player.base_price or 10000.0)
    state.highest_bidder_id = None
    state.timer_end = None
    state.paused_seconds_left = None
    state.started_at = None

    db.session.commit()
    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    action_name = 'SECOND_CHANCE_PLAYER_ACTIVATED' if is_sc else 'PLAYER_ACTIVATED'
    log_audit(admin_id, action_name, 'Player', player.id, None, player.name)
    return state

def start_bidding(admin_id=None):
    """Transition auction from PLAYER_PREVIEW to BIDDING state."""
    state = get_auction_state()
    if state.status != AuctionStatus.PLAYER_PREVIEW or not state.active_player_id:
        raise ValueError("No player currently in preview to start bidding.")

    timer_duration = int(SystemSettings.get_setting('timer_seconds', 10))
    state.status = AuctionStatus.BIDDING
    state.timer_seconds = timer_duration
    state.timer_end = datetime.utcnow() + timedelta(seconds=timer_duration)
    state.paused_seconds_left = None
    state.started_at = datetime.utcnow()

    db.session.commit()
    log_audit(admin_id, 'BIDDING_STARTED', 'Player', state.active_player_id, None, f"Timer: {timer_duration}s")
    return state

def pause_auction(admin_id=None):
    """Pause live bidding."""
    state = get_auction_state()
    if state.status != AuctionStatus.BIDDING:
        raise ValueError("Auction must be in BIDDING state to pause.")

    rem = state.remaining_seconds
    state.status = AuctionStatus.PAUSED
    state.paused_seconds_left = rem

    db.session.commit()
    log_audit(admin_id, 'AUCTION_PAUSED', 'Player', state.active_player_id, None, f"Seconds left: {rem}")
    return state

def resume_auction(admin_id=None):
    """Resume live bidding from PAUSED state."""
    state = get_auction_state()
    if state.status != AuctionStatus.PAUSED:
        raise ValueError("Auction must be in PAUSED state to resume.")

    rem = state.paused_seconds_left if state.paused_seconds_left is not None else 10
    state.status = AuctionStatus.BIDDING
    state.timer_end = datetime.utcnow() + timedelta(seconds=rem)
    state.paused_seconds_left = None

    db.session.commit()
    log_audit(admin_id, 'AUCTION_RESUMED', 'Player', state.active_player_id, None, f"Resumed with {rem}s")
    return state

def extend_timer(additional_seconds, admin_id=None):
    """Extend auction timer by additional seconds (e.g. +10s)."""
    state = get_auction_state()
    if state.status not in [AuctionStatus.BIDDING, AuctionStatus.PAUSED]:
        raise ValueError("Can only extend timer during BIDDING or PAUSED states.")

    if state.status == AuctionStatus.PAUSED:
        state.paused_seconds_left = (state.paused_seconds_left or 0) + additional_seconds
    else:
        if state.timer_end and state.timer_end > datetime.utcnow():
            state.timer_end += timedelta(seconds=additional_seconds)
        else:
            state.timer_end = datetime.utcnow() + timedelta(seconds=additional_seconds)

    db.session.commit()
    log_audit(admin_id, 'TIMER_EXTENDED', 'AuctionState', state.id, None, f"+{additional_seconds}s")
    return state

def get_next_bid_increment(current_bid):
    """
    Calculate bid increment step according to official SPL Section 44 business rules:
    - ₹10,000 – ₹20,000: +₹2,000
    - Above ₹20,000 – ₹50,000: +₹5,000
    - Above ₹50,000 – ₹1,00,000: +₹10,000
    - Above ₹1,00,000: +₹10,000
    """
    bid = float(current_bid or 0.0)
    if bid <= 20000.0:
        return 2000.0
    elif bid <= 50000.0:
        return 5000.0
    else:
        return 10000.0

def place_bid(franchise_id, bid_amount):
    """
    Submit a bid for the active player on behalf of a franchise.
    Performs comprehensive server-side validation.
    """
    state = get_auction_state()
    if state.status != AuctionStatus.BIDDING:
        raise ValueError("The auction is currently not accepting bids.")

    if not state.active_player_id:
        raise ValueError("No active player currently on auction.")

    player = Player.query.get(state.active_player_id)
    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    allowed_statuses = [PlayerStatus.AVAILABLE, PlayerStatus.UNSOLD] if is_sc else [PlayerStatus.AVAILABLE]
    if not player or player.status not in allowed_statuses:
        raise ValueError("Current auction player is invalid or no longer available.")

    franchise = Franchise.query.get(franchise_id)
    if not franchise or not franchise.is_active:
        raise ValueError("Franchise account is inactive or invalid.")

    # 0. Team Captain & Eligibility Validation (Strict enforcement: Captain Required to Bid)
    if not franchise.has_captain:
        raise ValueError("Team is NOT ELIGIBLE for bidding: Team Captain Required.")

    # 1. Squad Limit Validation (Max 15)
    if franchise.squad_count >= franchise.squad_limit:
        raise ValueError(f"Squad limit reached: {franchise.squad_count}/{franchise.squad_limit} players (Team Full).")

    # 2. Purse Validation
    bid_val = float(bid_amount)
    if franchise.remaining_purse < bid_val:
        raise ValueError(f"Insufficient purse for this bid. Remaining purse is Rs. {franchise.remaining_purse:,.0f}.")

    # 3. Double-Bid Prevention (Cannot bid against oneself)
    if state.highest_bidder_id == franchise.id:
        raise ValueError("Your franchise is already the highest bidder.")

    # 4. Increment & Required Bid Calculation
    increment = get_next_bid_increment(state.current_bid)
    if state.highest_bidder_id is None:
        # First bid rule: must be at least base_price
        required_bid = float(player.base_price or 10000.0)
    else:
        required_bid = state.current_bid + increment

    if bid_val < required_bid:
        raise ValueError(f"Bid no longer valid. Minimum required bid is Rs. {required_bid:,.0f}.")

    # 5. Execute Bid State Update
    state.current_bid = bid_val
    state.highest_bidder_id = franchise.id
    state.last_bid_at = datetime.utcnow()

    # Reset timer on every valid bid
    timer_duration = int(SystemSettings.get_setting('timer_seconds', 10))
    state.timer_seconds = timer_duration
    state.timer_end = datetime.utcnow() + timedelta(seconds=timer_duration)
    state.paused_seconds_left = None
    state.status = AuctionStatus.BIDDING

    # Record Immutable Bid Log
    bid_record = Bid(
        player_id=player.id,
        franchise_id=franchise.id,
        amount=bid_val
    )
    db.session.add(bid_record)
    db.session.commit()

    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    action_name = 'SECOND_CHANCE_BID_PLACED' if is_sc else 'BID_PLACED'
    log_audit(None, action_name, 'Bid', bid_record.id, None, f"{franchise.short_name} bid Rs. {bid_val:,.0f} for {player.name}")
    return state

def finalize_sold(admin_id=None):
    """
    Finalize current active player as SOLD to highest bidder.
    Executes an atomic database transaction. Sets status to SOLD.
    Guarantees idempotence so repeated calls do not double-deduct purse or duplicate transactions.
    """
    state = get_auction_state()
    if not state.active_player_id:
        raise ValueError("No active player to finalize.")

    # Idempotency check: if state is already marked SOLD for this player, return current state
    player = Player.query.get(state.active_player_id)
    winning_franchise = Franchise.query.get(state.highest_bidder_id) if state.highest_bidder_id else None

    if state.status == AuctionStatus.SOLD and player and player.status == PlayerStatus.SOLD and winning_franchise:
        return player, winning_franchise, player.sold_price

    if not state.highest_bidder_id or state.current_bid <= 0:
        raise ValueError("Cannot mark player as SOLD without a valid winning bid.")

    if not winning_franchise or not winning_franchise.is_active:
        raise ValueError("Winning franchise is invalid or inactive.")

    if winning_franchise.squad_count >= winning_franchise.squad_limit:
        raise ValueError(f"Winning franchise squad limit exceeded ({winning_franchise.squad_count}/{winning_franchise.squad_limit}).")

    if winning_franchise.remaining_purse < state.current_bid:
        raise ValueError(f"Winning franchise has insufficient purse (Rs. {winning_franchise.remaining_purse:,.0f}) for final bid Rs. {state.current_bid:,.0f}.")

    sold_price = state.current_bid

    # Atomic Transaction
    try:
        now = datetime.utcnow()
        is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
        player.status = PlayerStatus.SOLD
        player.sold_to = winning_franchise.id
        player.sold_price = sold_price
        player.auction_type = 'SECOND_CHANCE' if is_sc else 'PRIMARY'
        player.sold_at = now

        # Accurately recalculate winning franchise purse directly from squad
        winning_franchise.recalculate_purse()

        # Check for existing transaction to avoid duplicates
        transaction_record = Transaction.query.filter_by(
            player_id=player.id,
            franchise_id=winning_franchise.id,
            type='PLAYER_PURCHASE'
        ).first()

        if not transaction_record:
            transaction_record = Transaction(
                player_id=player.id,
                franchise_id=winning_franchise.id,
                amount=sold_price,
                type='PLAYER_PURCHASE',
                admin_id=admin_id
            )
            db.session.add(transaction_record)
        else:
            transaction_record.amount = sold_price

        # Set Auction State to SOLD with 10-second display timer (Requirements 1, 7, 8)
        state.status = AuctionStatus.SOLD
        state.timer_end = None
        state.paused_seconds_left = None
        state.sold_display_until = now + timedelta(seconds=10)

        db.session.commit()
        action_name = 'SECOND_CHANCE_PLAYER_SOLD' if is_sc else 'PLAYER_SOLD'
        log_audit(admin_id, action_name, 'Player', player.id, None, f"Sold to {winning_franchise.name} for Rs. {sold_price:,.0f} ({player.auction_type})")
        return player, winning_franchise, sold_price

    except Exception as e:
        db.session.rollback()
        raise RuntimeError(f"Database transaction failed during SOLD finalization: {str(e)}")

def finalize_unsold(admin_id=None):
    """Finalize current active player as UNSOLD."""
    state = get_auction_state()
    if not state.active_player_id:
        raise ValueError("No active player to mark UNSOLD.")

    player = Player.query.get(state.active_player_id)

    try:
        is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
        player.status = PlayerStatus.UNSOLD
        player.is_second_chance_eligible = True

        # Set Auction State to UNSOLD
        state.status = AuctionStatus.UNSOLD
        state.timer_end = None
        state.paused_seconds_left = None
        state.sold_display_until = None

        db.session.commit()
        action_name = 'SECOND_CHANCE_PLAYER_UNSOLD' if is_sc else 'PLAYER_UNSOLD'
        log_audit(admin_id, action_name, 'Player', player.id, None, f"Player {player.name} marked {player.status}")
        return player

    except Exception as e:
        db.session.rollback()
        raise RuntimeError(f"Database transaction failed during UNSOLD finalization: {str(e)}")

def clear_sold_player(admin_id=None):
    """
    Automatically remove sold player profile from Live Projection and active screen after 10 seconds.
    Transitions state to WAITING (or SECOND_CHANCE) and clears active player (Requirements 1, 7, 8).
    """
    state = get_auction_state()
    is_sc = SystemSettings.get_setting('second_chance_active') == 'true'
    state.status = AuctionStatus.SECOND_CHANCE if is_sc else AuctionStatus.WAITING
    state.active_player_id = None
    state.current_bid = 0.0
    state.highest_bidder_id = None
    state.timer_end = None
    state.sold_display_until = None
    state.paused_seconds_left = None
    db.session.commit()
    log_audit(admin_id, 'AUCTION_CLEARED_SOLD', 'AuctionState', state.id, None, '10s sold display completed. Cleared player from active auction screen.')
    return state

def reset_to_waiting(admin_id=None):
    """Reset global auction state back to WAITING."""
    state = get_auction_state()
    state.status = AuctionStatus.WAITING
    state.active_player_id = None
    state.current_bid = 0.0
    state.highest_bidder_id = None
    state.timer_end = None
    state.sold_display_until = None
    state.paused_seconds_left = None
    db.session.commit()
    log_audit(admin_id, 'AUCTION_RESET', 'AuctionState', state.id, None, 'Reset to WAITING')
    return state

def update_player_rule_number(player_id, new_rule_number, admin_id=None):
    """
    Update player rule number with strict duplicate prevention across the application (Requirements 4 & 5).
    """
    if not new_rule_number or not str(new_rule_number).strip():
        raise ValueError("New Rule Number is required.")
    clean_rule = str(new_rule_number).strip()

    player = Player.query.get(player_id)
    if not player:
        raise ValueError("Player not found.")

    existing = Player.query.filter(Player.roll_number.ilike(clean_rule), Player.id != player.id).first()
    if existing:
        raise ValueError(f"Rule Number '{clean_rule}' is already in use by player '{existing.name}'.")

    old_rule = player.roll_number
    player.roll_number = clean_rule

    # If player is captain of any franchise, update captain rule number too
    captain_team = Franchise.query.filter_by(captain_id=player.id).first()
    if captain_team:
        captain_team.captain_rule_number = clean_rule

    db.session.commit()
    log_audit(admin_id, 'PLAYER_RULE_NUMBER_UPDATED', 'Player', player.id, None, f"Rule number updated from '{old_rule}' to '{clean_rule}' for {player.name}")
    return player

# ==================== SECOND-CHANCE AUCTION SERVICES ====================

def find_second_chance_player_by_roll(roll_number):
    """
    Find player by roll number specifically for Second-Chance Auction.
    Must exist, have status UNSOLD, and be marked is_second_chance_eligible.
    Strictly protects against already sold players (Requirement 6).
    """
    if not roll_number:
        raise ValueError("Roll number is required.")

    player = Player.query.filter(Player.roll_number.ilike(str(roll_number).strip())).first()
    if not player:
        raise ValueError(f"PLAYER NOT FOUND. Roll number '{roll_number}' does not exist.")

    # Requirement 6: Sold Player Protection
    if player.is_sold or str(player.status).upper() == 'SOLD' or player.sold_to is not None:
        raise ValueError("Already Sold: This player cannot be auctioned again.")

    if player.status != PlayerStatus.UNSOLD:
        raise ValueError(f"PLAYER INELIGIBLE. Player '{player.name}' (#{player.roll_number}) is currently {player.status}.")

    if not player.is_second_chance_eligible:
        raise ValueError(f"NOT ELIGIBLE. Player '{player.name}' (#{player.roll_number}) has not been marked eligible for Second-Chance Auction.")

    return player

def start_second_chance_auction(admin_id):
    """Start Second-Chance Auction mode."""
    state = get_auction_state()
    SystemSettings.set_setting('second_chance_active', 'true')
    state.status = AuctionStatus.SECOND_CHANCE
    state.active_player_id = None
    state.current_bid = 0.0
    state.highest_bidder_id = None
    db.session.commit()

    log_audit(admin_id, 'SECOND_CHANCE_STARTED', 'AuctionState', state.id, None, 'Second-Chance Auction initiated')
    return state

def end_second_chance_auction(admin_id):
    """
    End Second-Chance Auction mode.
    All remaining eligible UNSOLD players become FINAL_UNSOLD.
    """
    state = get_auction_state()
    SystemSettings.set_setting('second_chance_active', 'false')

    # Convert remaining unsold players
    unsold_eligible = Player.query.filter_by(status=PlayerStatus.UNSOLD, is_second_chance_eligible=True).all()
    for p in unsold_eligible:
        p.status = PlayerStatus.FINAL_UNSOLD

    state.status = AuctionStatus.WAITING
    state.active_player_id = None
    state.current_bid = 0.0
    state.highest_bidder_id = None
    db.session.commit()

    log_audit(admin_id, 'SECOND_CHANCE_ENDED', 'AuctionState', state.id, None, f'Ended. {len(unsold_eligible)} players set to FINAL_UNSOLD')
    return state

# ==================== SQUAD VALIDATION & LOCKING SERVICES ====================

def validate_squads_integrity():
    """
    Run 10 strict database integrity checks prior to squad confirmation:
    1. No duplicate player exists.
    2. Every player belongs to max 1 franchise.
    3. No franchise exceeds 15 players.
    4. Purchase prices are valid.
    5. Total spending is correct.
    6. Purse cannot become negative.
    7. Every SOLD player has a franchise.
    8. Every franchise assignment has a purchase transaction.
    9. UNSOLD players are not assigned.
    10. Database totals match transaction totals.

    Returns (is_valid: bool, errors: list)
    """
    errors = []
    franchises = Franchise.query.filter_by(is_active=True).all()

    # 1 & 2. Duplicate / Multiple Franchise Assignment Check
    sold_players = Player.query.filter_by(status=PlayerStatus.SOLD).all()
    assigned_player_ids = set()
    for p in sold_players:
        if not p.sold_to:
            # 7. Every SOLD player must have a franchise
            errors.append(f"Validation Error: SOLD player '{p.name}' (#{p.roll_number}) has no assigned franchise.")
        if p.id in assigned_player_ids:
            # 1 & 2. Duplicate player assignment
            errors.append(f"Validation Error: Player '{p.name}' (#{p.roll_number}) assigned to multiple franchises.")
        assigned_player_ids.add(p.id)

        # 4. Valid Purchase Price (Captains have no purchase price / dash)
        if not p.is_captain and (p.sold_price is None or p.sold_price < 0):
            errors.append(f"Validation Error: Player '{p.name}' has invalid sold price ({p.sold_price}).")

    # 9. UNSOLD / AVAILABLE players not assigned
    unassigned_players = Player.query.filter(Player.status.in_([PlayerStatus.AVAILABLE, PlayerStatus.UNSOLD, PlayerStatus.FINAL_UNSOLD])).all()
    for p in unassigned_players:
        if p.sold_to is not None:
            errors.append(f"Validation Error: Unsold/Available player '{p.name}' (#{p.roll_number}) is assigned to franchise ID {p.sold_to}.")

    # 3, 5, 6. Franchise Level Checks
    total_db_spending = 0.0
    for f in franchises:
        # Mandatory Team Captain check
        if not f.has_captain:
            errors.append(f"Validation Error: Franchise '{f.name}' does not have a Team Captain. A Team Captain is mandatory for every squad.")

        # 3. Max squad limit
        if f.squad_count > f.squad_limit:
            errors.append(f"Validation Error: Franchise '{f.name}' exceeds squad limit ({f.squad_count}/{f.squad_limit}).")

        # 6. Purse non-negative
        if f.remaining_purse < 0:
            errors.append(f"Validation Error: Franchise '{f.name}' has negative remaining purse (Rs. {f.remaining_purse:,.0f}).")

        # 5. Total spending calculation accuracy
        actual_spent = sum((p.sold_price or 0.0) for p in f.sold_players)
        expected_remaining = f.starting_purse - actual_spent
        if abs(f.remaining_purse - expected_remaining) > 0.01:
            errors.append(f"Validation Error: Franchise '{f.name}' purse mismatch. Remaining: {f.remaining_purse}, Expected: {expected_remaining}.")

        total_db_spending += actual_spent

        # 8. Transaction record check (Captains have no purchase price / transaction)
        for p in f.sold_players:
            if not p.is_captain:
                tx = Transaction.query.filter_by(player_id=p.id, franchise_id=f.id, type='PLAYER_PURCHASE').first()
                if not tx:
                    errors.append(f"Validation Error: Player '{p.name}' in '{f.name}' lacks an official purchase transaction record.")

    # 10. DB totals vs Transaction totals match
    total_tx_spending = db.session.query(db.func.sum(Transaction.amount)).filter_by(type='PLAYER_PURCHASE').scalar() or 0.0
    if abs(total_db_spending - total_tx_spending) > 0.01:
        errors.append(f"Validation Error: Spending mismatch between Player records (Rs. {total_db_spending:,.0f}) and Transactions (Rs. {total_tx_spending:,.0f}).")

    return len(errors) == 0, errors

def confirm_and_lock_squads(admin_id):
    """Confirm and Lock final squads if integrity validation passes."""
    log_audit(admin_id, 'SQUAD_VALIDATION_STARTED', 'System', None, None, 'Starting final squad integrity validation')

    is_valid, errors = validate_squads_integrity()
    if not is_valid:
        log_audit(admin_id, 'SQUAD_VALIDATION_FAILED', 'System', None, None, f"Failed: {'; '.join(errors)}")
        raise ValueError(f"Squad integrity validation failed: {'; '.join(errors)}")

    SystemSettings.set_setting('squads_locked', 'true')
    state = get_auction_state()
    state.status = AuctionStatus.SQUADS_LOCKED
    db.session.commit()

    log_audit(admin_id, 'SQUADS_CONFIRMED', 'AuctionState', state.id, None, 'All 6 franchise squads confirmed')
    log_audit(admin_id, 'SQUADS_LOCKED', 'AuctionState', state.id, None, 'Squads locked permanently')
    return True

def unlock_squads_override(admin_id, reason):
    """Authorized Admin override unlock with required reason and audit log."""
    if not reason or not reason.strip():
        raise ValueError("An explicit reason is required to perform an Admin squad unlock override.")

    SystemSettings.set_setting('squads_locked', 'false')
    state = get_auction_state()
    state.status = AuctionStatus.WAITING
    db.session.commit()

    log_audit(admin_id, 'SQUADS_UNLOCKED', 'AuctionState', state.id, None, f"Override Reason: {reason.strip()}")
    return True


