#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import struct
import time
import tkinter as tk
from tkinter import messagebox, ttk
import serial
import serial.tools.list_ports


class HartProtocolHandler:
    """Ядро обмена данными по протоколу HART (Master)"""

    def __init__(self):
        self.ser = None

    def connect(self, port: str):
        """Открытие сессии связи с HART-модемом (1200 ODD, стандарт связи)"""
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = serial.Serial(
            port=port,
            baudrate=1200,
            parity=serial.PARITY_ODD,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=1.5,
        )

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _calculate_lrc(self, data: bytes) -> int:
        lrc = 0
        for byte in data:
            lrc ^= byte
        return lrc

    def send_command(self, cmd_num: int, data_bytes: bytes = b"") -> bytes:
        """Формирование и отправка кадра. Возвращает PDU ответа Slave-платы."""
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("COM-порт не открыт.")

        # Сборка кадра: Преамбула (5 байт) + Старт + Адрес + Команда + Длина + Данные
        preamble = b"\xFF" * 5
        pdu_body = struct.pack(
            f"BBBB{len(data_bytes)}s",
            0x02,
            0x80,
            cmd_num,
            len(data_bytes),
            data_bytes,
        )
        lrc = self._calculate_lrc(pdu_body)
        full_packet = preamble + pdu_body + bytes([lrc])

        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.ser.write(full_packet)
        self.ser.flush()

        time.sleep(0.15)
        response = self.ser.read(128)

        if not response:
            raise TimeoutError(f"Устройство не ответило на команду {cmd_num}")

        try:
            start_idx = response.index(0x06)
        except ValueError:
            raise ValueError("В потоке данных отсутствует байт ответа Slave (0x06)")

        pdu_reply = response[start_idx:]
        if len(pdu_reply) < 3:
            raise ValueError("Кадр ответа слишком короткий")

        # Валидация контрольной суммы ответа
        received_lrc = pdu_reply[-1]
        if received_lrc != self._calculate_lrc(pdu_reply[:-1]):
            raise ValueError("Ошибка контрольной суммы LRC при приеме данных")

        return pdu_reply


class ConfiguratorApp(tk.Tk):
    """Графический интерфейс конфигуратора промышленного оборудования"""

    def __init__(self):
        super().__init__()
        self.title("Универсальный ПК-конфигуратор уровнемера")
        self.geometry("740x640")
        self.resizable(True, True)

        self.auto_refresh_enabled = False
        self.rowconfigure(3, weight=1)
        self.columnconfigure(0, weight=1)

        self.hart = HartProtocolHandler()
        self._create_widgets()
        self.refresh_com_ports()

    def _create_widgets(self):
        style = ttk.Style()
        style.theme_use("clam")

        font_normal = ("Arial", 10)
        font_bold = ("Arial", 11, "bold")
        self.font_digits = ("Arial", 22, "bold")

        # --- Блок связи ---
        conn_frame = ttk.LabelFrame(self, text=" Настройка связи ", padding=10)
        conn_frame.grid(row=0, column=0, padx=15, pady=5, sticky="ew")

        ttk.Label(conn_frame, text="COM Порт:", font=font_normal).pack(
            side="left", padx=5
        )
        self.port_combobox = ttk.Combobox(
            conn_frame, width=15, font=font_normal, state="readonly"
        )
        self.port_combobox.pack(side="left", padx=5)

        ttk.Button(
            conn_frame, text="🔄 Обновить", width=11, command=self.refresh_com_ports
        ).pack(side="left", padx=5)
        self.btn_connect = ttk.Button(
            conn_frame, text="Подключить", width=12, command=self.toggle_connection
        )
        self.btn_connect.pack(side="left", padx=5)

        self.lbl_status = ttk.Label(
            conn_frame, text="Отключено", foreground="red", font=font_bold
        )
        self.lbl_status.pack(side="right", padx=10)

        # --- Блок мониторинга ---
        mon_frame = ttk.LabelFrame(
            self, text=" Текущие измерения прибора ", padding=10
        )
        mon_frame.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        mon_frame.columnconfigure(0, weight=1)
        mon_frame.columnconfigure(1, weight=1)

        # Уровень
        lbl_sub = ttk.Frame(mon_frame)
        lbl_sub.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")
        ttk.Label(lbl_sub, text="УРОВЕНЬ ЖИДКОСТИ:", font=font_bold).pack(anchor="w")
        self.lbl_level = ttk.Label(
            lbl_sub, text="0.0000 м", font=self.font_digits, foreground="blue"
        )
        self.lbl_level.pack(anchor="w", pady=5)

        # Ток
        cur_sub = ttk.Frame(mon_frame)
        cur_sub.grid(row=0, column=1, padx=10, pady=5, sticky="nsew")
        ttk.Label(cur_sub, text="ТОК В ПЕТЛЕ (4-20 мА):", font=font_bold).pack(
            anchor="w"
        )
        self.lbl_current = ttk.Label(
            cur_sub, text="4.000 мА", font=self.font_digits, foreground="green"
        )
        self.lbl_current.pack(anchor="w", pady=5)

        # Температура
        t_sub = ttk.Frame(mon_frame)
        t_sub.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        ttk.Label(t_sub, text="TЕМПЕРАТУРА ДАТЧИКА:", font=font_bold).pack(anchor="w")
        self.lbl_temp = ttk.Label(
            t_sub, text="0.0 °C", font=self.font_digits, foreground="purple"
        )
        self.lbl_temp.pack(anchor="w", pady=5)

        ttk.Button(
            mon_frame, text="Опросить датчики вручную", command=self.read_process_data
        ).grid(row=2, column=0, columnspan=2, pady=5, sticky="ew")
        self.btn_auto = ttk.Button(
            mon_frame, text="▶ Запустить автоопрос", command=self.toggle_auto_refresh
        )
        self.btn_auto.grid(row=3, column=0, columnspan=2, pady=5, sticky="ew")

        # --- Блок калибровки ---
        settings_frame = ttk.LabelFrame(
            self, text=" Окно настроек и калибровки ", padding=10
        )
        settings_frame.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        settings_frame.columnconfigure(2, weight=1)

        ttk.Label(settings_frame, text="Плотность среды (кг/м³):", font=font_normal).grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )
        self.density_entry = ttk.Entry(settings_frame, width=12, font=font_normal)
        self.density_entry.insert(0, "1000.0")
        self.density_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(
            settings_frame, text="Записать плотность (Команда 13)", command=self.write_density
        ).grid(row=0, column=2, padx=10, pady=5, sticky="w")

        ttk.Label(settings_frame, text="Макс. диапазон (мм):", font=font_normal).grid(
            row=1, column=0, padx=5, pady=5, sticky="w"
        )
        self.range_entry = ttk.Entry(settings_frame, width=12, font=font_normal)
        self.range_entry.insert(0, "1000.0")
        self.range_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(
            settings_frame, text="Записать диапазон (Команда 12)", command=self.write_range
        ).grid(row=1, column=2, padx=10, pady=5, sticky="w")

        # --- Лог ---
        log_frame = ttk.LabelFrame(self, text=" Терминал событий и лог ", padding=10)
        log_frame.grid(row=3, column=0, padx=15, pady=5, sticky="nsew")
        self.log_text = tk.Text(log_frame, height=5, font=("Consolas", 9), bg="#F0F0F0")
        self.log_text.pack(fill="both", expand=True)

    def refresh_com_ports(self):
        ports = serial.tools.list_ports.comports()
        ports_list = [port.device for port in ports]
        self.port_combobox["values"] = ports_list
        if ports_list:
            self.port_combobox.current(0)
            self._log(f"Доступные порты обновлены. Найдено: {len(ports_list)}")
        else:
            self.port_combobox.set("")
            self._log("Активные COM-порты в системе не найдены.")

    def _log(self, message: str):
        self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_text.see(tk.END)

    def toggle_connection(self):
        if self.btn_connect["text"] == "Подключить":
            port = self.port_combobox.get().strip()
            if not port:
                messagebox.showwarning("Внимание", "Выберите активный порт связи.")
                return
            try:
                self.hart.connect(port)
                self.lbl_status.config(text="ПОДКЛЮЧЕНО", foreground="green")
                self.btn_connect.config(text="Отключить")
                self.port_combobox.config(state="disabled")
                self._log(f"Установлена сессия связи: {port}")
                self.read_device_passport()
            except Exception as e:
                messagebox.showerror("Ошибка связи", f"Не удалось занять порт {port}:\n{e}")
                self._log(f"Сбой инициализации {port}: {e}")
        else:
            if self.auto_refresh_enabled:
                self.toggle_auto_refresh()
            self.hart.disconnect()
            self.lbl_status.config(text="Отключено", foreground="red")
            self.btn_connect.config(text="Подключить")
            self.port_combobox.config(state="readonly")
            self._log("Сессия связи завершена.")

    def read_device_passport(self):
        """Команда 0: Идентификация устройства"""
        try:
            pdu = self.hart.send_command(0)
            data = pdu[6:-1]
            addr = data[0] if len(data) > 0 else 0
            man_id = data[1] if len(data) > 1 else 0
            dev_type = data[2] if len(data) > 2 else 0

            man_str = "Standard Device" if man_id == 0x01 else f"Vendor ID: {man_id}"
            self._log(f"HART Device ID получен. Адрес: {addr}, Производитель: {man_str}, Тип: {dev_type}")
        except Exception as e:
            self._log(f"Идентификация устройства не удалась: {e}")

    def read_process_data(self):
        """Команда 3: Чтение динамических переменных процесса"""
        try:
            try:
                current_range_mm = float(self.range_entry.get())
            except ValueError:
                current_range_mm = 1000.0

            pdu3 = self.hart.send_command(3)
            level_ratio = struct.unpack_from(">f", pdu3, len(pdu3) - 10)[0]
            temperature_c = struct.unpack_from(">f", pdu3, len(pdu3) - 5)[0]

            range_m = current_range_mm / 1000.0
            actual_level_m = level_ratio * range_m
            current_ma = 4.0 + (level_ratio * 16.0)

            self.lbl_level.config(text=f"{actual_level_m:.4f} м")
            self.lbl_current.config(text=f"{current_ma:.3f} мА")
            self.lbl_temp.config(text=f"{temperature_c:.1f} °C")

            if not self.auto_refresh_enabled:
                self._log(f"Измерения: {actual_level_m:.4f} м (Диапазон: {current_range_mm} мм)")
        except Exception as e:
            if self.auto_refresh_enabled:
                self.toggle_auto_refresh()
            messagebox.showerror("Ошибка", f"Потеря связи при опросе датчиков:\n{e}")
            self._log(f"Ошибка циклического чтения: {e}")

    def toggle_auto_refresh(self):
        if not self.auto_refresh_enabled:
            if self.btn_connect["text"] == "Подключить":
                messagebox.showwarning("Внимание", "Требуется активное подключение.")
                return
            self.auto_refresh_enabled = True
            self.btn_auto.config(text="⏸ Остановить автоопрос")
            self._log("Запущен фоновый циклический опрос (Период: 1.5 сек)")
            self.auto_refresh_loop()
        else:
            self.auto_refresh_enabled = False
            self.btn_auto.config(text="▶ Запустить автоопрос")
            self._log("Фоновый опрос остановлен.")

    def auto_refresh_loop(self):
        if self.auto_refresh_enabled:
            self.read_process_data()
            self.after(1500, self.auto_refresh_loop)

    def write_density(self):
        """Команда 13: Запись калибровочной плотности жидкости"""
        try:
            val = float(self.density_entry.get())
            data_payload = struct.pack(">f", val)
            pdu = self.hart.send_command(13, data_payload)
            saved_density = struct.unpack_from(">f", pdu, len(pdu) - 5)[0]
            self._log(f"Калибровка: плотность {saved_density:.1f} кг/м³ записана успешно")
            time.sleep(0.05)
            self.read_process_data()
            messagebox.showinfo("Успех", f"Параметр плотности изменен: {saved_density} кг/м³")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось передать параметры калибровки:\n{e}")
            self._log(f"Ошибка записи плотности: {e}")

    def write_range(self):
        """Команда 12: Запись верхнего значения диапазона (шкалы)"""
        try:
            val = float(self.range_entry.get())
            data_payload = struct.pack(">f", val)
            pdu = self.hart.send_command(12, data_payload)
            saved_range = struct.unpack_from(">f", pdu, len(pdu) - 5)[0]
            self._log(f"Конфигурация: шкала {saved_range:.1f} мм записана успешно")
            time.sleep(0.05)
            self.read_process_data()
            messagebox.showinfo("Успех", f"Предел шкалы изменен: {saved_range} мм")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось обновить предел шкалы:\n{e}")
            self._log(f"Ошибка записи диапазона: {e}")

if __name__ == "__main__":
    app = ConfiguratorApp()
    app.mainloop()
