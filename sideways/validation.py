import pandas as pd

def validate_data(df: pd.DataFrame, required_columns=None) -> bool:
    """데이터프레임의 필수 컬럼 및 결측치, 이상치 검증."""
    if required_columns is None:
        required_columns = ['close', 'volume']
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
        if df[col].isnull().any():
            raise ValueError(f"Null values in column: {col}")
    return True
