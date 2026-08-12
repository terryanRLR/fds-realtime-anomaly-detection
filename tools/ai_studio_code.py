import os
import sys
import traceback

def consolidate_py_files():
    output_file = "consolidated_codes.md"
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

        print(f"🔍 총 {len(py_files)}개의 .py 파일을 발견했습니다. 작업을 시작합니다...\n")

        with open(output_file, 'w', encoding='utf-8') as outfile:
            outfile.write("# 📂 통합 파이썬 코드 모음\n\n")
            
            for filename in sorted(py_files):
                print(f"-> [처리 중] {filename}")
                outfile.write(f"## 📄 {filename}\n\n")
                outfile.write("```python\n")
                
                # 인코딩 에러(한글 깨짐/불러오기 실패) 방지 로직
                content = ""
                try:
                    # 1차 시도: UTF-8
                    with open(filename, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                except UnicodeDecodeError:
                    # 2차 시도: CP949 (윈도우 기본 한글 인코딩)
                    with open(filename, 'r', encoding='cp949', errors='replace') as infile:
                        content = infile.read()

                outfile.write(content)
                outfile.write("\n```\n\n---\n\n")

        print(f"\n✅ 성공적으로 완료되었습니다!")
        print(f"📄 결과 저장 위치: {os.path.abspath(output_file)}")

    except Exception as e:
        print("\n❌ 작업 중 에러가 발생했습니다!")
        print(f"에러 메시지: {e}")
        
        # 상세 에러 내용을 error_log.txt 파일로 저장
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write("=== 에러 발생 로그 ===\n")
            f.write(traceback.format_exc())
            
        print(f"\n⚠️ 상세 에러 내용이 '{log_file}' 파일에 저장되었습니다.")

if __name__ == "__main__":
    try:
        consolidate_py_files()
    finally:
        # 무슨 일이 있어도 창이 바로 닫히지 않고 키 입력을 기다림
        print("\n" + "="*50)
        input("엔터(Enter) 키를 누르면 창이 닫힙니다...")