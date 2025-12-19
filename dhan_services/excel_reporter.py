import pandas as pd
import xlwings as xw


class ExcelReporter:
    def __init__(self, file_path="AlgoTrade.xlsx"):
        self.wb = xw.Book(file_path)
        self.live_sheet = self.wb.sheets["Live_Trading"]
        self.completed_sheet = self.wb.sheets["completed_orders"]

        self.live_sheet.range("A2:Z100").value = None
        self.completed_sheet.range("A2:Z100").value = None

    def update_live_orders(self, orderbook):
        df = pd.DataFrame(orderbook).T
        self.live_sheet.range("A1").value = df

    def update_completed_orders(self, completed_orders):
        df = pd.DataFrame(completed_orders)
        self.completed_sheet.range("A1").value = df

    def save(self):
        self.wb.save()
