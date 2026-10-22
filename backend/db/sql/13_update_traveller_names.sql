-- Full names for the five travellers added in 10_more_travellers.sql.
-- (10 already contains the full names for fresh databases; this brings existing databases in line.)
BEGIN;
UPDATE dim_passenger SET passenger_name = 'Srija Panchagnula'   WHERE passenger_id = 'P10';
UPDATE dim_passenger SET passenger_name = 'Mahesh Ammanaganti'  WHERE passenger_id = 'P11';
UPDATE dim_passenger SET passenger_name = 'Harshini Bhavisetty' WHERE passenger_id = 'P12';
UPDATE dim_passenger SET passenger_name = 'Manish Galigini'     WHERE passenger_id = 'P13';
UPDATE dim_passenger SET passenger_name = 'Rohith Gunda'        WHERE passenger_id = 'P14';
COMMIT;
