#!/usr/bin/env python3
"""
高鐵退票機器人
用於批次取消高鐵訂位

使用方式：
  # 使用設定檔
  python cancel_bot.py
  
  # 指定設定檔
  python cancel_bot.py -c my_cancel_config.toml
  
  # 直接指定單筆退票（不需設定檔）
  python cancel_bot.py --id A123456789 --pnr 12345678
  
  # 跳過確認直接退票
  python cancel_bot.py -y
  
  # 互動模式（手動輸入）
  python cancel_bot.py -i
"""

import argparse
import os
import sys

# 確保從腳本所在目錄載入
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

# Load .env file for API keys
try:
    from dotenv import load_dotenv
    import pathlib
    env_path = pathlib.Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path, override=True)
except ImportError:
    pass

from services.thsrc_cancel import THSRCCancel


def interactive_mode():
    """互動模式：手動輸入退票資訊"""
    print("\n" + "="*60)
    print("🚄 高鐵退票機器人 - 互動模式")
    print("="*60)
    
    cancellations = []
    
    while True:
        print(f"\n📝 輸入第 {len(cancellations) + 1} 筆退票資料")
        print("-" * 40)
        
        roc_id = input("身分證字號 (輸入 q 結束): ").strip()
        if roc_id.lower() == 'q':
            break
        
        if len(roc_id) != 10:
            print("⚠️ 身分證字號格式不正確（應為10碼）")
            continue
        
        pnr = input("訂位代號: ").strip()
        if not pnr:
            print("⚠️ 訂位代號不能為空")
            continue
        
        cancellations.append({
            'id': roc_id.upper(),
            'pnr': pnr.upper(),
            'enabled': True
        })
        
        print(f"✅ 已加入: {roc_id[:4]}****{roc_id[-2:]} / {pnr}")
        
        cont = input("\n繼續輸入下一筆？(Y/n): ").strip().lower()
        if cont == 'n':
            break
    
    if not cancellations:
        print("❌ 沒有輸入任何退票資料")
        return
    
    print(f"\n📋 共 {len(cancellations)} 筆待退票資料:")
    for i, item in enumerate(cancellations, 1):
        print(f"   {i}. {item['id'][:4]}****{item['id'][-2:]} / {item['pnr']}")
    
    confirm = input("\n確定要開始退票嗎？(y/N): ").strip().lower()
    if confirm != 'y':
        print("⏭️ 取消操作")
        return
    
    # 建立服務並執行
    cancel_service = THSRCCancel()
    cancel_service.cancellations = cancellations
    cancel_service.settings['confirm_before_cancel'] = False  # 已經確認過了
    cancel_service.run()


def main():
    parser = argparse.ArgumentParser(
        description='高鐵退票機器人',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  # 使用設定檔批次退票
  python cancel_bot.py -c cancel_config.toml

  # 直接指定單筆退票
  python cancel_bot.py --id A123456789 --pnr 12345678

  # 互動模式手動輸入
  python cancel_bot.py -i

  # 跳過確認直接執行
  python cancel_bot.py -y
        """
    )
    
    parser.add_argument(
        '-c', '--config',
        default='cancel_config.toml',
        help='設定檔路徑 (預設: cancel_config.toml)'
    )
    
    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='互動模式：手動輸入退票資訊'
    )
    
    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='跳過確認，直接執行退票'
    )
    
    parser.add_argument(
        '--id',
        help='直接指定身分證字號（需搭配 --pnr）'
    )
    
    parser.add_argument(
        '--pnr',
        help='直接指定訂位代號（需搭配 --id）'
    )
    
    parser.add_argument(
        '--repeat',
        type=int,
        default=1,
        help='重複執行次數 (預設: 1)'
    )
    
    args = parser.parse_args()
    
    # 互動模式
    if args.interactive:
        interactive_mode()
        return
    
    # 直接指定參數模式
    if args.id and args.pnr:
        print("\n📌 使用命令列參數模式")
        
        for i in range(args.repeat):
            if args.repeat > 1:
                print(f"\n🔄 執行第 {i + 1}/{args.repeat} 次")
            
            cancel_service = THSRCCancel(args.config)
            cancel_service.cancellations = [{
                'id': args.id.upper(),
                'pnr': args.pnr.upper(),
                'enabled': True
            }]
            
            if args.yes:
                cancel_service.settings['confirm_before_cancel'] = False
            
            success = cancel_service.run()
            
            if success and i < args.repeat - 1:
                import time
                print(f"\n⏳ 等待 5 秒後執行下一次...")
                time.sleep(5)
        
        return
    
    # 使用設定檔模式
    if not os.path.exists(args.config):
        print(f"❌ 找不到設定檔: {args.config}")
        print("\n💡 提示:")
        print("   1. 複製 cancel_config.toml 並填入退票資料")
        print("   2. 或使用 -i 進入互動模式")
        print("   3. 或使用 --id 和 --pnr 直接指定")
        sys.exit(1)
    
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"\n🔄 執行第 {i + 1}/{args.repeat} 次")
        
        cancel_service = THSRCCancel(args.config)
        
        if args.yes:
            cancel_service.settings['confirm_before_cancel'] = False
        
        success = cancel_service.run()
        
        if success and i < args.repeat - 1:
            import time
            delay = cancel_service.settings.get('delay_between', 5)
            print(f"\n⏳ 等待 {delay} 秒後執行下一次...")
            time.sleep(delay)


if __name__ == '__main__':
    main()
