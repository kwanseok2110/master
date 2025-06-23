import random
from collections import Counter

# --- 1단계 ~ 3단계 함수들은 이전과 완전히 동일합니다 ---
def generate_plausible_combo():
    """기본 규칙을 만족하는 '그럴듯한' 로또 번호 1세트를 생성합니다."""
    while True:
        numbers = random.sample(range(1, 46), 6)
        evens = sum(1 for n in numbers if n % 2 == 0)
        if evens == 0 or evens == 6: continue
        if not (108 <= sum(numbers) <= 168): continue
        sorted_nums = sorted(numbers)
        is_consecutive = any(sorted_nums[i+1] == sorted_nums[i] + 1 and sorted_nums[i+2] == sorted_nums[i] + 2 for i in range(4))
        if is_consecutive: continue
        return sorted_nums

def create_simulated_history(num_records):
    """지정된 개수만큼의 가상 역사 데이터를 생성합니다."""
    print(f"가상 로또 기록 {num_records}개를 생성하여 통계 기반을 마련합니다...")
    history = [generate_plausible_combo() for _ in range(num_records)]
    print("가상 기록 생성을 완료했습니다.")
    return history

def analyze_and_create_pool(history):
    """생성된 가상 데이터를 분석하여 유력 후보군(potential pool)을 생성합니다."""
    all_win_numbers = [num for sublist in history for num in sublist]
    freq = Counter(all_win_numbers)
    hot_numbers = {num for num, count in freq.most_common(20)}
    recent_numbers = set([num for sublist in history[-10:] for num in sublist])
    all_possible_nums = set(range(1, 46))
    cold_numbers = all_possible_nums - recent_numbers
    potential_pool = sorted(list(hot_numbers.union(cold_numbers)))
    
    print("\n--- 시뮬레이션 데이터 분석 결과 ---")
    print(f"✨ 총 {len(potential_pool)}개의 유력 후보군을 선정했습니다.")
    
    return potential_pool, history[-1]

def is_combination_valid(combo, last_win_numbers):
    """하나의 조합이 모든 고급 필터를 통과하는지 검사합니다."""
    evens = sum(1 for n in combo if n % 2 == 0)
    if evens == 0 or evens == 6: return False
    if not (108 <= sum(combo) <= 168): return False
    sorted_combo = sorted(combo)
    if any(sorted_combo[i+1] == sorted_combo[i] + 1 and sorted_combo[i+2] == sorted_combo[i] + 2 for i in range(4)): return False
    lows = sum(1 for n in combo if 1 <= n <= 22)
    if lows < 2 or lows > 4: return False
    carry_over_count = len(set(combo).intersection(set(last_win_numbers)))
    if carry_over_count > 2: return False
    return True

def generate_final_sets(pool, last_win_numbers, num_of_sets):
    """모든 규칙을 만족하는 최종 로또 번호 세트를 생성합니다."""
    final_sets = []
    attempts = 0
    max_attempts = 50000

    while len(final_sets) < num_of_sets and attempts < max_attempts:
        attempts += 1
        candidate_set = random.sample(pool, 6)
        if not is_combination_valid(candidate_set, last_win_numbers): continue
        if any(len(set(candidate_set).intersection(set(s))) >= 2 for s in final_sets): continue
        final_sets.append(sorted(candidate_set))
        print(f"  ... {len(final_sets)}번째 유효 조합 생성 완료.")

    if len(final_sets) < num_of_sets:
        print(f"\n⚠️ 경고: 요청하신 {num_of_sets}개 중 {len(final_sets)}개만 생성했습니다.")
        
    return final_sets

# --- 메인 실행 부분 ---
if __name__ == "__main__":
    print("★★  KWANSUK's 로또 생성 프로그램 [2025-06-23]  ★")
    print("본 프로그램은 https://aistudio.google.com/prompts/new_chat 자동생성 코드로 작성됨")
    simulated_history = create_simulated_history(100000)
    potential_pool, last_simulated_numbers = analyze_and_create_pool(simulated_history)
    
    sets_to_generate = 5
    
    print(f"\n고정된 {sets_to_generate}세트 생성을 시작합니다. 최적의 조합을 찾고 있습니다...")
    recommended_sets = generate_final_sets(potential_pool, last_simulated_numbers, sets_to_generate)
    
    print("\n" + "="*55)
    print(f"🎉 최종 추천 로또 번호 {len(recommended_sets)}세트 🎉")
    print("경고: 이 번호는 통계적 재미를 위한 것이며 당첨을 보장하지 않습니다.")
    print("="*55)

    if recommended_sets:
        # 👇 이 부분이 수정되었습니다.
        for i, s in enumerate(recommended_sets, 1):
            average = sum(s) / 6
            # 1. 각 숫자를 2자리 문자열로 변환 (예: 6 -> "06")
            formatted_numbers = [str(num).zfill(2) for num in s]
            # 2. 변환된 문자열들을 쉼표와 공백으로 연결
            numbers_string = ", ".join(formatted_numbers)
            # 3. 최종 포맷팅된 문자열을 출력
            print(f"  추천 {i}세트: {numbers_string}  (평균: {average:.1f})")
    else:
        print("  생성된 추천 번호가 없습니다.")

    input("\n프로그램을 종료하려면 Enter 키를 누르세요...")