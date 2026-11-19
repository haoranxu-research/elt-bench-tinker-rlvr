# Local customer orders

Load both CSV streams into the isolated warehouse. Write `load.json` with a
`sources` object mapping `customers.csv` and `orders.csv` to null (all rows) or to
integer row limits for debugging. Run the load stage to produce:

- raw_customers(customer_id INTEGER, name TEXT)
- raw_orders(order_id INTEGER, customer_id INTEGER, amount REAL)

An empty CSV field loads as NULL. After load, write each output as one SQLite
SELECT over the raw tables with the named columns in order:

- `customer_totals.sql`: customer_id, name, order_count, total_amount. Include
  every customer, even with no orders. For a customer with no orders use zero
  for count and amount. Keep a missing name as NULL.
- `order_totals.sql`: order_count, average_amount. Return one row across all orders.

The transform stage materializes both tables. Use execution feedback to correct
any errors. Then submit the pipeline in a later turn.
