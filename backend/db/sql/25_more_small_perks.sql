-- Two more small perks (additive): same-day standby and an overweight-bag allowance.
--   * Standby: included by fares with same-day change/standby and by Silver and above; it can be released (75) or
--     bought (1,800) when the traveller lacks it.
--   * Overweight allowance (up to 70 lb): never included; it can be bought (6,500), not released.
-- The 300-point cap on small-perk releases is unchanged. With standby (75) the four release values add to 375, so
-- the cap now genuinely applies.
BEGIN;

INSERT INTO dim_benefit (benefit_id, benefit_name, benefit_type, bag_ordinal, seat_class,
                         perkflex_release_points, perkflex_redeem_points, release_eligible_flag, cash_addon_cents) VALUES
  ('PERK_STANDBY',    'Same-day standby',          'PERK', NULL, NULL, 75, 1800, true,  0),
  ('PERK_OVERWEIGHT', 'Overweight bag allowance',  'PERK', NULL, NULL,  0, 6500, false, 10000)
ON CONFLICT (benefit_id) DO NOTHING;

CREATE OR REPLACE FUNCTION pf_perk_source(p_booking text, p_benefit text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT CASE p_benefit
    WHEN 'PERK_LANE' THEN
      CASE WHEN f.priority_lane_flag THEN 'FARE' WHEN p.tier_status IN ('SILVER','GOLD','PLATINUM') THEN 'TIER' END
    WHEN 'PERK_DRINK' THEN
      CASE WHEN f.premium_drink_flag THEN 'FARE' WHEN p.tier_status IN ('GOLD','PLATINUM') THEN 'TIER' END
    WHEN 'PERK_BOARDING' THEN
      CASE WHEN f.boarding_group = 'Group 1' THEN 'FARE' WHEN p.tier_status IN ('SILVER','GOLD','PLATINUM') THEN 'TIER' END
    WHEN 'PERK_STANDBY' THEN
      CASE WHEN f.same_day_change_standby_flag THEN 'FARE' WHEN p.tier_status IN ('SILVER','GOLD','PLATINUM') THEN 'TIER' END
    -- PERK_OVERWEIGHT: never included, so it is always for sale
  END
  FROM fact_booking b
  JOIN dim_fare f ON f.fare_id = b.fare_id
  JOIN dim_passenger p ON p.passenger_id = b.passenger_id
  WHERE b.booking_id = p_booking;
$$;

COMMIT;
