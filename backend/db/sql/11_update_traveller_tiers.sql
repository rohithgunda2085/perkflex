-- Tier updates: Mahesh and Rohith are Silver, Srija is Gold, Harshini is Platinum.
-- Benefit rows hold ONE effective row per bag ordinal / seat (pf_bag_allowance sums them), so where a
-- tier supersedes a card or fare benefit the older row is replaced rather than added to.
BEGIN;

UPDATE dim_passenger SET tier_status = 'SILVER',   demo_story = 'Silver member on a refundable Choice Preferred fare: first bag covered, Extra Legroom opens at check-in' WHERE passenger_id = 'P11';
UPDATE dim_passenger SET tier_status = 'SILVER',   demo_story = 'Silver member with a Choice Extra trip. Flight booked, ready to make the most of every perk' WHERE passenger_id = 'P14';
UPDATE dim_passenger SET tier_status = 'GOLD',     demo_story = 'Gold member with a Premier card: Gold covers two bags and Extra Legroom, the card adds nothing on top' WHERE passenger_id = 'P10';
UPDATE dim_passenger SET tier_status = 'PLATINUM', demo_story = 'Platinum member with a Priority card: three bags and Extra Legroom are covered, only one bag planned' WHERE passenger_id = 'P12';

-- Gold (Srija, B10) and Platinum (Harshini, B12) hold an Extra Legroom seat at booking.
UPDATE dim_seat SET seat_status = 'AVAILABLE' WHERE seat_id IN ('F01-19B', 'F01-6A');
UPDATE fact_booking SET seat_id = 'F01-3B' WHERE booking_id = 'B10';
UPDATE fact_booking SET seat_id = 'F01-3C' WHERE booking_id = 'B12';
UPDATE dim_seat SET seat_status = 'ASSIGNED' WHERE seat_id IN ('F01-3B', 'F01-3C');

-- Srija: Gold replaces her Premier card rows.
DELETE FROM fact_passenger_benefit WHERE passenger_benefit_id IN ('PB16', 'PB17');
-- Harshini: Platinum replaces her Priority card rows.
DELETE FROM fact_passenger_benefit WHERE passenger_benefit_id IN ('PB19', 'PB20', 'PB21');

INSERT INTO fact_passenger_benefit (passenger_benefit_id, booking_id, benefit_id, benefit_source, source_code, eligible_quantity, available_from, used_quantity, released_quantity, granted_quantity) VALUES
  -- Srija (Gold): no bags planned, seated in Extra Legroom
  ('PB25', 'B10', 'BAG1',    'TIER', 'GOLD',     1, 'BOOKING', 0, 0, 0),
  ('PB26', 'B10', 'BAG2',    'TIER', 'GOLD',     1, 'BOOKING', 0, 0, 0),
  ('PB27', 'B10', 'SEAT_XL', 'TIER', 'GOLD',     1, 'BOOKING', 1, 0, 0),
  -- Harshini (Platinum): one bag planned of three covered, seated in Extra Legroom
  ('PB28', 'B12', 'BAG1',    'TIER', 'PLATINUM', 1, 'BOOKING', 1, 0, 0),
  ('PB29', 'B12', 'BAG2',    'TIER', 'PLATINUM', 1, 'BOOKING', 0, 0, 0),
  ('PB30', 'B12', 'BAG3',    'TIER', 'PLATINUM', 1, 'BOOKING', 0, 0, 0),
  ('PB31', 'B12', 'SEAT_XL', 'TIER', 'PLATINUM', 1, 'BOOKING', 1, 0, 0),
  -- Mahesh (Silver): first bag from the tier; Extra Legroom unlocks at check-in (Preferred seat stays from the fare)
  ('PB32', 'B11', 'BAG1',    'TIER', 'SILVER',   1, 'BOOKING', 1, 0, 0),
  ('PB33', 'B11', 'SEAT_XL', 'TIER', 'SILVER',   1, 'CHECKIN', 0, 0, 0);
-- Rohith (Silver) needs no new rows: his Choice Extra fare already covers two bags and Extra Legroom.

COMMIT;
