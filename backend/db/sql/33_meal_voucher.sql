-- Airport meal voucher (additive): a buy-only small perk.
--   * Never included by a fare or status, so it is always for sale (pf_perk_source returns NULL for it).
--   * It cannot be released (release_eligible_flag = false, release points 0).
--   * Concept note: Southwest gives meal vouchers only after airline-caused delays of 3 hours or more, on request.
--     This perk is a PerkFlex concept add-on, not a Southwest benefit.
BEGIN;
INSERT INTO dim_benefit (benefit_id, benefit_name, benefit_type, bag_ordinal, seat_class,
                         perkflex_release_points, perkflex_redeem_points, release_eligible_flag, cash_addon_cents) VALUES
  ('PERK_MEAL', 'Airport meal voucher', 'PERK', NULL, NULL, 0, 1500, false, 1200)
ON CONFLICT (benefit_id) DO NOTHING;
COMMIT;
