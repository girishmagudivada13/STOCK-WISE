
import os
import mysql.connector
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="StockWise",
    page_icon="📦",
    layout="wide"
)

st.title("📦 StockWise")
st.subheader("Inventory Management & Sales Analytics")
st.caption("Manage products, track sales, and monitor stock levels.")


def get_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database="stockwise_db"
    )


def load_products():
    conn = get_connection()
    try:
        return pd.read_sql("SELECT * FROM products ORDER BY product_id DESC", conn)
    finally:
        conn.close()


def load_sales():
    conn = get_connection()
    try:
        query = """
        SELECT s.sale_id, p.product_name, s.quantity,
               s.unit_price, s.total_amount, s.sale_date
        FROM sales s
        JOIN products p ON s.product_id = p.product_id
        ORDER BY s.sale_date DESC
        """
        return pd.read_sql(query, conn)
    finally:
        conn.close()


try:
    products = load_products()
    sales = load_sales()
except mysql.connector.Error as error:
    st.error("Could not connect to MySQL. Check your server and credentials.")
    st.code(str(error))
    st.stop()


page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Manage Products", "Record Sale", "Sales History"]
)


if page == "Dashboard":
    st.header("Inventory Dashboard")

    total_products = len(products)
    total_units = int(products["stock_quantity"].sum()) if not products.empty else 0
    low_stock = (
        int((products["stock_quantity"] <= products["reorder_level"]).sum())
        if not products.empty else 0
    )
    revenue = float(sales["total_amount"].sum()) if not sales.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Products", total_products)
    c2.metric("Units in Stock", total_units)
    c3.metric("Low-Stock Products", low_stock)
    c4.metric("Recorded Sales Revenue", f"₹{revenue:,.2f}")

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Stock by Product")
        if not products.empty:
            st.bar_chart(
                products.set_index("product_name")["stock_quantity"]
            )
        else:
            st.info("Add products to see the stock chart.")

    with right:
        st.subheader("Sales by Product")
        if not sales.empty:
            chart = sales.groupby("product_name")["total_amount"].sum()
            st.bar_chart(chart)
        else:
            st.info("Record a sale to see sales analytics.")

    st.subheader("Low-Stock Alerts")
    if not products.empty:
        alerts = products[
            products["stock_quantity"] <= products["reorder_level"]
        ]
        if alerts.empty:
            st.success("All products are above their reorder levels.")
        else:
            st.dataframe(alerts, use_container_width=True)

    st.subheader("Product Inventory")
    st.dataframe(products, use_container_width=True)


elif page == "Manage Products":
    st.header("Manage Products")

    with st.form("product_form", clear_on_submit=True):
        name = st.text_input("Product Name")
        category = st.selectbox(
            "Category",
            ["Electronics", "Stationery", "Clothing", "Food", "Other"]
        )
        price = st.number_input("Unit Price (₹)", min_value=0.01, value=100.0)
        quantity = st.number_input("Initial Stock", min_value=0, step=1)
        reorder = st.number_input("Reorder Level", min_value=0, value=5, step=1)
        submitted = st.form_submit_button("Add Product")

    if submitted:
        if not name.strip():
            st.warning("Please enter a product name.")
        else:
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO products
                    (product_name, category, price, stock_quantity, reorder_level)
                    VALUES (%s, %s, %s, %s, %s)""",
                    (name.strip(), category, price, quantity, reorder)
                )
                conn.commit()
                st.success("Product added successfully!")
                st.rerun()
            except mysql.connector.Error as error:
                st.error(f"Could not add product: {error}")
            finally:
                if conn and conn.is_connected():
                    conn.close()

    st.subheader("Existing Products")
    st.dataframe(products, use_container_width=True)


elif page == "Record Sale":
    st.header("Record a Sale")

    if products.empty:
        st.info("Add a product before recording a sale.")
    else:
        available = products[products["stock_quantity"] > 0]

        if available.empty:
            st.warning("No products currently have stock available.")
        else:
            options = {
                f"{row.product_name} (Stock: {row.stock_quantity})": row.product_id
                for row in available.itertuples()
            }

            with st.form("sale_form"):
                selected = st.selectbox("Product", list(options.keys()))
                product_id = options[selected]
                product = available[
                    available["product_id"] == product_id
                ].iloc[0]

                qty = st.number_input(
                    "Quantity Sold",
                    min_value=1,
                    max_value=int(product["stock_quantity"]),
                    step=1
                )

                st.write(f"Unit price: ₹{float(product['price']):,.2f}")
                st.write(f"Sale total: ₹{float(product['price']) * qty:,.2f}")

                sold = st.form_submit_button("Save Sale")

            if sold:
                conn = None
                try:
                    conn = get_connection()
                    conn.start_transaction()
                    cursor = conn.cursor()

                    cursor.execute(
                        "SELECT stock_quantity, price FROM products "
                        "WHERE product_id = %s FOR UPDATE",
                        (product_id,)
                    )
                    current = cursor.fetchone()

                    if current is None or current[0] < qty:
                        conn.rollback()
                        st.error("Insufficient stock. Refresh and try again.")
                    else:
                        unit_price = float(current[1])
                        total = unit_price * qty

                        cursor.execute(
                            """INSERT INTO sales
                            (product_id, quantity, unit_price, total_amount)
                            VALUES (%s, %s, %s, %s)""",
                            (product_id, qty, unit_price, total)
                        )
                        cursor.execute(
                            """UPDATE products
                            SET stock_quantity = stock_quantity - %s
                            WHERE product_id = %s""",
                            (qty, product_id)
                        )
                        conn.commit()
                        st.success("Sale recorded and stock updated!")
                        st.rerun()

                except mysql.connector.Error as error:
                    if conn and conn.is_connected():
                        conn.rollback()
                    st.error(f"Could not record sale: {error}")
                finally:
                    if conn and conn.is_connected():
                        conn.close()


elif page == "Sales History":
    st.header("Sales History")

    if sales.empty:
        st.info("No sales have been recorded yet.")
    else:
        st.metric("Total Sales Transactions", len(sales))
        st.dataframe(sales, width="stretch")

        st.subheader("Revenue by Product")
        st.bar_chart(sales.groupby("product_name")["total_amount"].sum())

        csv = sales.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Sales CSV",
            data=csv,
            file_name="stockwise_sales.csv",
            mime="text/csv"
        )
