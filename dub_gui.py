# dub_gui.py

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pysrt
import dub_pipeline

LANG_MAP = {
    "Turkish": "tr",
    "Arabic": "ar",
    "Russian": "ru",
    "Hindi": "hi",
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Polish": "pl",
    "Dutch": "nl",
    "Czech": "cs",
    "Chinese": "zh-cn",
    "Korean": "ko",
    "Hungarian": "hu"
}


class DubbingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AI Local Video Dubber Studio")
        self.geometry("1060x860")
        self.minsize(900, 700)

        self.subs_cache = None
        self.trans_subs_cache = None

        self.video_path_var = tk.StringVar()
        self.folder_name_var = tk.StringVar(value="output_run_1")
        self.model_name_var = tk.StringVar(value="qwen3.5:9b-instruct")
        self.src_lang_var = tk.StringVar(value="Turkish")
        self.tgt_lang_var = tk.StringVar(value="Hindi")

        self.setup_ui()

    def setup_ui(self):
        # 1. TOP CONFIGURATION CARD
        config_frame = ttk.LabelFrame(self, text=" 1. Project Setup ", padding=12)
        config_frame.pack(fill="x", padx=15, pady=6)

        # Video selector
        ttk.Label(config_frame, text="Input Video:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(config_frame, textvariable=self.video_path_var, width=65).grid(row=0, column=1, padx=6, pady=4)
        ttk.Button(config_frame, text="Browse...", command=self.browse_video).grid(row=0, column=2, pady=4)

        # Output folder & model name
        ttk.Label(config_frame, text="Output Folder:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(config_frame, textvariable=self.folder_name_var, width=25).grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(config_frame, text="Ollama Model:").grid(row=1, column=1, sticky="e", pady=4)
        ttk.Entry(config_frame, textvariable=self.model_name_var, width=22).grid(row=1, column=2, sticky="w", padx=6, pady=4)

        # Languages selector
        ttk.Label(config_frame, text="Source Language:").grid(row=2, column=0, sticky="w", pady=4)
        src_combo = ttk.Combobox(config_frame, textvariable=self.src_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=15)
        src_combo.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(config_frame, text="Target Language:").grid(row=2, column=1, sticky="e", pady=4)
        tgt_combo = ttk.Combobox(config_frame, textvariable=self.tgt_lang_var, values=list(LANG_MAP.keys()), state="readonly", width=15)
        tgt_combo.grid(row=2, column=2, sticky="w", padx=6, pady=4)

        # 2. SUBTITLE EDITOR CARD
        editor_frame = ttk.LabelFrame(self, text=" 2. Subtitle Editor (Source & Translation) ", padding=12)
        editor_frame.pack(fill="both", expand=True, padx=15, pady=6)

        cols = ("idx", "start", "end", "src_text", "tgt_text")
        self.tree = ttk.Treeview(editor_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("idx", text="#")
        self.tree.heading("start", text="Start")
        self.tree.heading("end", text="End")
        self.tree.heading("src_text", text="Source (Whisper - Editable)")
        self.tree.heading("tgt_text", text="Target (Translation - Editable)")

        self.tree.column("idx", width=40, anchor="center")
        self.tree.column("start", width=85, anchor="center")
        self.tree.column("end", width=85, anchor="center")
        self.tree.column("src_text", width=380)
        self.tree.column("tgt_text", width=380)

        tree_scroll = ttk.Scrollbar(editor_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="top", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # In-line Editor Controls
        edit_control_frame = ttk.Frame(editor_frame, padding=6)
        edit_control_frame.pack(fill="x", side="bottom")

        # Edit Source Input
        src_edit_frame = ttk.Frame(edit_control_frame)
        src_edit_frame.pack(fill="x", pady=2)
        ttk.Label(src_edit_frame, text="Edit Source Line:", width=18).pack(side="left")
        self.src_edit_entry = ttk.Entry(src_edit_frame)
        self.src_edit_entry.pack(side="left", fill="x", expand=True, padx=6)

        # Edit Target Input
        tgt_edit_frame = ttk.Frame(edit_control_frame)
        tgt_edit_frame.pack(fill="x", pady=2)
        ttk.Label(tgt_edit_frame, text="Edit Target Line:", width=18).pack(side="left")
        self.tgt_edit_entry = ttk.Entry(tgt_edit_frame)
        self.tgt_edit_entry.pack(side="left", fill="x", expand=True, padx=6)

        self.save_btn = ttk.Button(edit_control_frame, text="Save Selected Row Edits", command=self.save_row_edit)
        self.save_btn.pack(side="right", pady=4)

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # 3. THREE-STAGE WORKFLOW BUTTONS
        btn_frame = ttk.Frame(self, padding=8)
        btn_frame.pack(fill="x", padx=15)

        self.step1_btn = ttk.Button(
            btn_frame, 
            text="Step 1: Extract & Transcribe (Whisper)", 
            command=self.start_step1_transcribe
        )
        self.step1_btn.pack(side="left", padx=4, fill="x", expand=True)

        self.step2_btn = ttk.Button(
            btn_frame, 
            text="Step 2: Translate Clean Source (Ollama)", 
            state="disabled", 
            command=self.start_step2_translate
        )
        self.step2_btn.pack(side="left", padx=4, fill="x", expand=True)

        self.step3_btn = ttk.Button(
            btn_frame, 
            text="Step 3: Synthesize & Dub Video (XTTS-v2)", 
            state="disabled", 
            command=self.start_step3_dub
        )
        self.step3_btn.pack(side="left", padx=4, fill="x", expand=True)

        # 4. CONSOLE ACTIVITY LOG
        log_frame = ttk.LabelFrame(self, text=" Activity Log ", padding=8)
        log_frame.pack(fill="x", padx=15, pady=6)

        self.log_text = tk.Text(log_frame, height=6, state="disabled", bg="#1E1E1E", fg="#D4D4D4", font=("Menlo", 10))
        self.log_text.pack(fill="x")

    def browse_video(self):
        file_selected = filedialog.askopenfilename(
            filetypes=[("Video Files", "*.mp4 *.mov *.mkv *.avi"), ("All Files", "*.*")]
        )
        if file_selected:
            self.video_path_var.set(file_selected)

    def log(self, message):
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _append)

    def on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        vals = self.tree.item(selected[0], "values")
        
        self.src_edit_entry.delete(0, tk.END)
        self.src_edit_entry.insert(0, vals[3])

        self.tgt_edit_entry.delete(0, tk.END)
        self.tgt_edit_entry.insert(0, vals[4])

    def save_row_edit(self):
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(self.tree.item(selected[0], "values")[0])
        new_src = self.src_edit_entry.get().strip()
        new_tgt = self.tgt_edit_entry.get().strip()

        # Update in-memory objects
        if self.subs_cache:
            for item in self.subs_cache:
                if item.index == idx:
                    item.text = new_src
                    break

        if self.trans_subs_cache:
            for item in self.trans_subs_cache:
                if item.index == idx:
                    item.text = new_tgt
                    break

        # Update table UI
        vals = list(self.tree.item(selected[0], "values"))
        vals[3] = new_src
        vals[4] = new_tgt
        self.tree.item(selected[0], values=vals)

        self.log(f"Row #{idx} updated.")

    def set_buttons_state(self, s1="normal", s2="normal", s3="normal"):
        self.step1_btn.configure(state=s1)
        self.step2_btn.configure(state=s2)
        self.step3_btn.configure(state=s3)

    # -------------------------------------------------------------------
    # STEP 1: EXTRACT & TRANSCRIBE
    # -------------------------------------------------------------------
    def start_step1_transcribe(self):
        video_path = self.video_path_var.get().strip()
        if not os.path.exists(video_path):
            messagebox.showerror("Error", f"Invalid video file path:\n'{video_path}'")
            return

        self.set_buttons_state("disabled", "disabled", "disabled")
        threading.Thread(target=self._step1_worker, daemon=True).start()

    def _step1_worker(self):
        try:
            video_path = self.video_path_var.get().strip()
            out_dir = self.folder_name_var.get().strip()
            os.makedirs(out_dir, exist_ok=True)

            src_name = self.src_lang_var.get()
            src_code = LANG_MAP[src_name]

            audio_path = os.path.join(out_dir, "original_audio.wav")
            src_srt_path = os.path.join(out_dir, f"{src_name.lower()}_subtitles.srt")

            # 1. Extract audio
            dub_pipeline.extract_audio(video_path, audio_path, log_fn=self.log)

            # 2. Transcribe
            self.subs_cache = dub_pipeline.transcribe_to_srt(
                audio_path, src_srt_path, src_name, src_code, log_fn=self.log
            )
            self.trans_subs_cache = None  # Reset downstream translation

            def _populate():
                for row in self.tree.get_children():
                    self.tree.delete(row)
                for item in self.subs_cache:
                    self.tree.insert("", "end", values=(
                        item.index,
                        str(item.start),
                        str(item.end),
                        item.text,
                        ""  # Target empty until Step 2
                    ))
                self.set_buttons_state("normal", "normal", "disabled")
                self.log("\nStep 1 Done! Review and correct the 'Source' text in the table above before translating.")
                messagebox.showinfo(
                    "Transcription Ready",
                    "Transcription complete!\n\nReview the source text in the table above, fix any misheard words, and then click 'Step 2: Translate Clean Source'."
                )

            self.after(0, _populate)

        except Exception as e:
            self.log(f"Error during Step 1: {e}")
            self.after(0, lambda: self.set_buttons_state("normal", "disabled", "disabled"))

    # -------------------------------------------------------------------
    # STEP 2: TRANSLATE WITH OLLAMA
    # -------------------------------------------------------------------
    def start_step2_translate(self):
        if not self.subs_cache:
            messagebox.showwarning("Warning", "Run Step 1 first to generate subtitles.")
            return

        self.set_buttons_state("disabled", "disabled", "disabled")
        threading.Thread(target=self._step2_worker, daemon=True).start()

    def _step2_worker(self):
        try:
            out_dir = self.folder_name_var.get().strip()
            src_name = self.src_lang_var.get()
            tgt_name = self.tgt_lang_var.get()
            model_name = self.model_name_var.get()

            # Save any edits made to the source text before passing to Ollama
            src_srt_path = os.path.join(out_dir, f"{src_name.lower()}_subtitles.srt")
            self.subs_cache.save(src_srt_path, encoding="utf-8")
            self.log(f"Saved edited source subtitles to {src_srt_path}")

            tgt_srt_path = os.path.join(out_dir, f"{tgt_name.lower()}_subtitles.srt")

            # 3. Translate using the user-edited source cache
            self.trans_subs_cache = dub_pipeline.translate_subtitles_ollama(
                self.subs_cache, tgt_srt_path, model_name, src_name, tgt_name, log_fn=self.log
            )

            def _refresh_table():
                for row in self.tree.get_children():
                    self.tree.delete(row)
                for src_item, tgt_item in zip(self.subs_cache, self.trans_subs_cache):
                    self.tree.insert("", "end", values=(
                        src_item.index,
                        str(src_item.start),
                        str(src_item.end),
                        src_item.text,
                        tgt_item.text
                    ))
                self.set_buttons_state("normal", "normal", "normal")
                self.log("\nStep 2 Done! Review the translation lines, then proceed to Dubbing.")
                messagebox.showinfo(
                    "Translation Ready", 
                    "Translation complete!\n\nYou can now make any adjustments to the target language lines, then click 'Step 3: Synthesize & Dub Video'."
                )

            self.after(0, _refresh_table)

        except Exception as e:
            self.log(f"Error during Step 2: {e}")
            self.after(0, lambda: self.set_buttons_state("normal", "normal", "disabled"))

    # -------------------------------------------------------------------
    # STEP 3: DUB & REMUX VIDEO (XTTS-V2)
    # -------------------------------------------------------------------
    def start_step3_dub(self):
        if not self.trans_subs_cache:
            messagebox.showwarning("Warning", "Run Step 2 first to translate subtitles.")
            return

        self.set_buttons_state("disabled", "disabled", "disabled")
        threading.Thread(target=self._step3_worker, daemon=True).start()

    def _step3_worker(self):
        try:
            out_dir = self.folder_name_var.get().strip()
            video_path = self.video_path_var.get().strip()
            tgt_name = self.tgt_lang_var.get()
            tgt_code = LANG_MAP[tgt_name]

            # Save latest target subtitle edits to disk
            tgt_srt_path = os.path.join(out_dir, f"{tgt_name.lower()}_subtitles.srt")
            self.trans_subs_cache.save(tgt_srt_path, encoding="utf-8")
            self.log(f"Saved approved target subtitles to {tgt_srt_path}")

            audio_path = os.path.join(out_dir, "original_audio.wav")
            dubbed_audio_path = os.path.join(out_dir, "dubbed_audio.wav")
            voice_sample_path = os.path.join(out_dir, "voice_sample.wav")
            temp_dir = os.path.join(out_dir, "temp_segments")
            os.makedirs(temp_dir, exist_ok=True)

            ext = os.path.splitext(video_path)[1]
            final_video_path = os.path.join(out_dir, f"output_dubbed_video{ext}")

            # 4. XTTS Voice Synthesis
            dub_pipeline.dub_with_xtts(
                self.trans_subs_cache, audio_path, dubbed_audio_path, voice_sample_path, temp_dir, tgt_code, log_fn=self.log
            )

            # 5. FFmpeg Remux
            dub_pipeline.remux_video(video_path, dubbed_audio_path, final_video_path, log_fn=self.log)

            def _done():
                self.set_buttons_state("normal", "normal", "normal")
                messagebox.showinfo("Success", f"Dubbing complete!\nSaved to:\n{final_video_path}")

            self.after(0, _done)

        except Exception as e:
            self.log(f"Error during Step 3: {e}")
            self.after(0, lambda: self.set_buttons_state("normal", "normal", "normal"))


if __name__ == "__main__":
    app = DubbingApp()
    app.mainloop()