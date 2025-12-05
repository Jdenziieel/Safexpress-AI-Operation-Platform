"""
Database Cleanup Script
Removes duplicate database files and consolidates to database/ subdirectory
"""
import os
import shutil

def cleanup_databases():
    """Remove duplicate database files from root backend directory"""
    backend_root = os.path.dirname(__file__)
    
    # Files to remove from root (keeping only in database/ subdirectory)
    files_to_remove = [
        os.path.join(backend_root, "chat_sessions.db"),
        os.path.join(backend_root, "documents.db")
    ]
    
    print("="*70)
    print("Database Cleanup Script")
    print("="*70)
    print("\nThis script will remove duplicate database files from backend/")
    print("All databases will be kept in backend/database/ subdirectory\n")
    
    removed_count = 0
    
    for file_path in files_to_remove:
        if os.path.exists(file_path):
            try:
                # Get file size for reporting
                size = os.path.getsize(file_path)
                size_kb = size / 1024
                
                # Remove the file
                os.remove(file_path)
                
                filename = os.path.basename(file_path)
                print(f"✅ Removed: {filename} ({size_kb:.2f} KB)")
                removed_count += 1
            except Exception as e:
                print(f"❌ Failed to remove {os.path.basename(file_path)}: {e}")
        else:
            print(f"⏭️  Not found: {os.path.basename(file_path)} (already cleaned)")
    
    print(f"\n{'='*70}")
    print(f"Cleanup Summary: {removed_count} file(s) removed")
    print(f"{'='*70}")
    
    # Verify database/ subdirectory exists
    db_dir = os.path.join(backend_root, "database")
    if os.path.exists(db_dir):
        print(f"\n✅ Database directory exists: {db_dir}")
        
        # List current database files
        db_files = [f for f in os.listdir(db_dir) if f.endswith('.db')]
        if db_files:
            print(f"\nCurrent database files in database/:")
            for db_file in db_files:
                db_path = os.path.join(db_dir, db_file)
                size = os.path.getsize(db_path)
                size_kb = size / 1024
                print(f"  - {db_file} ({size_kb:.2f} KB)")
        else:
            print("\n⚠️  No .db files found in database/ directory")
            print("   Databases will be created automatically on first use")
    else:
        print(f"\n❌ Database directory not found: {db_dir}")
    
    print(f"\n{'='*70}")
    print("Next steps:")
    print("1. Run migration: py backend/database/migrations/add_token_tracking.py")
    print("2. Restart backend: py backend/app.py")
    print("3. Test uploads to verify 'Uploaded By' shows correct user name")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    cleanup_databases()
