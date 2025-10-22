"""
HS Code Audit Tool - GUI Version
Double-click to run, select files through interface
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess
import sys
import json
import tempfile

class AuditGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("HS Code Audit Tool")
        self.root.geometry("900x700")

        # 配置网格权重，支持自适应
        root.grid_rowconfigure(6, weight=1)  # 日志框所在行可伸缩
        root.grid_columnconfigure(1, weight=1)  # 中间列可伸缩

        # PDF file selection
        tk.Label(root, text="PDF Invoice File:", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=10)
        self.pdf_path = tk.StringVar()
        tk.Entry(root, textvariable=self.pdf_path, font=("Arial", 11)).grid(row=0, column=1, sticky="ew", padx=10, pady=10)
        tk.Button(root, text="Browse...", command=self.select_pdf, font=("Arial", 11)).grid(row=0, column=2, padx=10, pady=10)

        # Excel file selection
        tk.Label(root, text="Excel Mapping File:", font=("Arial", 11, "bold")).grid(row=1, column=0, sticky="w", padx=10, pady=10)
        self.excel_path = tk.StringVar()
        tk.Entry(root, textvariable=self.excel_path, font=("Arial", 11)).grid(row=1, column=1, sticky="ew", padx=10, pady=10)
        tk.Button(root, text="Browse...", command=self.select_excel, font=("Arial", 11)).grid(row=1, column=2, padx=10, pady=10)

        # Excel column name configuration
        tk.Label(root, text="Excel - Item Column:", font=("Arial", 11, "bold")).grid(row=2, column=0, sticky="w", padx=10, pady=10)
        self.item_col = tk.StringVar(value="Item")
        tk.Entry(root, textvariable=self.item_col, width=20, font=("Arial", 11)).grid(row=2, column=1, sticky="w", padx=10, pady=10)

        tk.Label(root, text="Excel - HScode Column:", font=("Arial", 11, "bold")).grid(row=3, column=0, sticky="w", padx=10, pady=10)
        self.hscode_col = tk.StringVar(value="HScode USA")
        tk.Entry(root, textvariable=self.hscode_col, width=20, font=("Arial", 11)).grid(row=3, column=1, sticky="w", padx=10, pady=10)

        # PDF table column order configuration (竖向显示)
        tk.Label(root, text="PDF Table Columns:", font=("Arial", 11, "bold")).grid(row=4, column=0, sticky="nw", padx=10, pady=10)
        tk.Label(root, text="(one per line)", font=("Arial", 10), fg="gray").grid(row=4, column=0, sticky="nw", padx=10, pady=(30, 0))

        # 使用Text控件，支持多行输入
        column_frame = tk.Frame(root)
        column_frame.grid(row=4, column=1, columnspan=2, sticky="ew", padx=10, pady=10)

        self.column_text = tk.Text(column_frame, height=9, width=30, font=("Arial", 12))
        self.column_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 添加滚动条
        column_scrollbar = tk.Scrollbar(column_frame, command=self.column_text.yview)
        column_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.column_text.config(yscrollcommand=column_scrollbar.set)

        # 默认列顺序（每行一个）
        default_columns = "customer\norder_no\nu11_code\ncustomer_no\nsanhua_no\nquantity\nunit_price\namount"
        self.column_text.insert("1.0", default_columns)

        # Start button
        tk.Button(root, text="Start Audit", command=self.run_audit,
                 bg="#4CAF50", fg="white", font=("Arial", 13, "bold"),
                 width=20, height=2).grid(row=5, column=1, pady=20)

        # Status display (支持自适应)
        tk.Label(root, text="Log Output:", font=("Arial", 11, "bold")).grid(row=6, column=0, sticky="nw", padx=10, pady=(0, 5))

        status_frame = tk.Frame(root)
        status_frame.grid(row=6, column=0, columnspan=3, sticky="nsew", padx=10, pady=(30, 10))

        self.status_text = tk.Text(status_frame, state="disabled", wrap=tk.WORD, font=("Arial", 11))
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 添加滚动条
        status_scrollbar = tk.Scrollbar(status_frame, command=self.status_text.yview)
        status_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.config(yscrollcommand=status_scrollbar.set)

    def select_pdf(self):
        filename = filedialog.askopenfilename(
            title="Select PDF Invoice File",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if filename:
            self.pdf_path.set(filename)

    def select_excel(self):
        filename = filedialog.askopenfilename(
            title="Select Excel Mapping File",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if filename:
            self.excel_path.set(filename)

    def log(self, message):
        """Display message in status box"""
        self.status_text.config(state="normal")
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state="disabled")
        self.root.update()

    def run_audit(self):
        pdf_file = self.pdf_path.get()
        excel_file = self.excel_path.get()

        if not pdf_file or not excel_file:
            messagebox.showerror("Error", "Please select both PDF and Excel files!")
            return

        if not os.path.exists(pdf_file):
            messagebox.showerror("Error", f"PDF file not found: {pdf_file}")
            return

        if not os.path.exists(excel_file):
            messagebox.showerror("Error", f"Excel file not found: {excel_file}")
            return

        # Clear status
        self.status_text.config(state="normal")
        self.status_text.delete(1.0, tk.END)
        self.status_text.config(state="disabled")

        # Parse column order from Text widget (one per line)
        column_order_str = self.column_text.get("1.0", tk.END).strip()
        if not column_order_str:
            messagebox.showerror("Error", "Please specify PDF table column order!")
            return

        # 每行一个列名
        column_list = [col.strip() for col in column_order_str.split('\n') if col.strip()]
        if not column_list:
            messagebox.showerror("Error", "Invalid column order format!")
            return

        # Create temporary column_config.json
        config_data = {"default": column_list}

        # Get the directory where column_config.json should be
        if getattr(sys, 'frozen', False):
            # Running as exe: put config file next to exe
            config_dir = os.path.dirname(sys.executable)
        else:
            # Running as script: put config file in project root
            config_dir = os.path.dirname(__file__)

        config_path = os.path.join(config_dir, "column_config.json")

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            self.log(f"Created column config: {column_list}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create column config: {e}")
            return

        self.log("=" * 60)
        self.log("Starting HS Code audit...")
        self.log(f"PDF file: {pdf_file}")
        self.log(f"Excel file: {excel_file}")
        self.log("=" * 60)

        # Build command
        if getattr(sys, 'frozen', False):
            # Running as exe
            audit_exe = os.path.join(os.path.dirname(sys.executable), 'audit.exe')
            if os.path.exists(audit_exe):
                cmd = [audit_exe, pdf_file, excel_file,
                       "--item-col", self.item_col.get(),
                       "--hscode-col", self.hscode_col.get()]
            else:
                # Single-file packaged, call audit.py directly
                cmd = None  # Will handle below
        else:
            # Running as Python script
            audit_script = os.path.join(os.path.dirname(__file__), 'audit.py')
            cmd = [sys.executable, audit_script, pdf_file, excel_file,
                   "--item-col", self.item_col.get(),
                   "--hscode-col", self.hscode_col.get()]

        # If single-file packaged exe (no separate audit.exe), call audit module directly
        if cmd is None:
            import audit as audit_module
            try:
                original_argv = sys.argv
                sys.argv = ['audit.py', pdf_file, excel_file,
                            '--item-col', self.item_col.get(),
                            '--hscode-col', self.hscode_col.get()]
                audit_module.main()
                sys.argv = original_argv
                self.log("\n✓ Audit completed!")
                messagebox.showinfo("Complete", "Audit completed! Please check result.csv in the output directory.")
                return
            except SystemExit as e:
                sys.argv = original_argv
                if e.code == 0:
                    self.log("\n✓ Audit completed with no errors.")
                    messagebox.showinfo("Complete", "Audit completed! All HScodes match correctly.")
                else:
                    self.log("\n✗ Audit completed with errors found.")
                    messagebox.showwarning("Complete", "Audit completed with errors! Please check result.csv")
                return
            except Exception as e:
                sys.argv = original_argv
                self.log(f"\n✗ Error: {str(e)}")
                messagebox.showerror("Error", f"Audit failed: {str(e)}")
                return

        # Run command via subprocess
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8'
            )

            # Display output in real-time
            for line in iter(process.stdout.readline, ''):
                if line:
                    self.log(line.rstrip())

            process.wait()

            if process.returncode == 0:
                self.log("\n✓ Audit completed with no errors.")
                messagebox.showinfo("Complete", "Audit completed! All HScodes match correctly.")
            else:
                self.log("\n✗ Audit completed with errors found.")
                messagebox.showwarning("Complete", "Audit completed with errors! Please check result.csv")

        except Exception as e:
            self.log(f"\n✗ Error: {str(e)}")
            messagebox.showerror("Error", f"Audit failed: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = AuditGUI(root)
    root.mainloop()
