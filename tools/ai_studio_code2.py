import os
import json
import traceback

def create_ipynb_from_py():
    output_file = "consolidated_codes.ipynb"
    log_file = "error_log.txt"

    try:
        # 현재 스크립트 자신의 파일명 구하기
        current_script = os.path.basename(__file__)
        
        # 현재 폴더의 .py 파일 목록 추출 (자기 자신은 제외)
        py_files = [f for f in os.listdir('.') if f.endswith('.py') and f != current_script]

        if not py_files:
            print("⚠️ 현재 폴더에 합칠 .py 파일이 없습니다.")
            print("스크립트 파일이 정리하고 싶은 .py 파일들과 같은 폴더에 있는지 확인해 주세요.")
            return

        print(f"🔍 총 {len(py_files)}개의 .py 파일을 발견했습니다. 주피터 노트북(.ipynb) 변환을 시작합니다...\n")

        # 주피터 노트북 기본 셀 구성
        cells = [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# 📂 통합 파이썬 코드 모음\n",
                    "\n",
                    "폴더 내의 `.py` 파일들을 하나의 주피터 노트북으로 합친 파일입니다."
                ]
            }
        ]

        for filename in sorted(py_files):
            print(f"-> [처리 중] {filename}")
            
            # 1. 파일 이름 (마크다운 셀)
            md_cell = {
                "cell_type": "markdown",
                "metadata": {},
                "source": [f"## 📄 {filename}"]
            }
            cells.append(md_cell)

            # 2. 파일 내용 읽기 (인코딩 안전 처리)
            content = ""
            try:
                with open(filename, 'r', encoding='utf-8') as infile:
                    content = infile.read()
            except UnicodeDecodeError:
                with open(filename, 'r', encoding='cp949', errors='replace') as infile:
                    content = infile.read()

            # 줄바꿈(\n)을 유지한 채 리스트로 분할 (주피터 규격)
            lines = content.splitlines(keepends=True)
            if not lines:
                lines = ["# (빈 파일입니다)"]

            # 3. 파이썬 코드 (코드 셀)
            code_cell = {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": lines
            }
            cells.append(code_cell)

        # 주피터 노트북 (.ipynb) 전체 데이터 구조
        notebook_data = {
            "cells": cells,
            "metadata": {
                "language_info": {
                    "name": "python"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 2
        }

        # .ipynb 파일 작성
        with open(output_file, 'w', encoding='utf-8') as outfile:
            json.dump(notebook_data, outfile, ensure_ascii=False, indent=2)

        print(f"\n✅ 성공적으로 변환되었습니다!")
        print(f"📄 결과 파일: {os.path.abspath(output_file)}")

    except Exception as e:
        print("\n❌ 작업 중 에러가 발생했습니다!")
        print(f"에러 메시지: {e}")
        
        # 에러 내용을 error_log.txt 파일로 저장
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write("=== 에러 발생 로그 ===\n")
            f.write(traceback.format_exc())
            
        print(f"\n⚠️ 상세 에러 내용이 '{log_file}' 파일에 저장되었습니다.")

if __name__ == "__main__":
    try:
        create_ipynb_from_py()
    finally:
        print("\n" + "="*50)
        input("엔터(Enter) 키를 누르면 창이 닫힙니다...")