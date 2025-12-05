# Generated migration to add UUID user_id field

import uuid
from django.db import migrations, models


def generate_uuid_for_existing_users(apps, schema_editor):
    """Generate UUIDs for existing users that don't have one."""
    CustomUser = apps.get_model('api', 'CustomUser')
    for user in CustomUser.objects.all():
        if not user.user_id:
            user.user_id = str(uuid.uuid4())
            user.save(update_fields=['user_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_add_admin_activity_log'),
    ]

    operations = [
        # First add the field as nullable
        migrations.AddField(
            model_name='customuser',
            name='user_id',
            field=models.CharField(max_length=36, null=True, blank=True),
        ),
        
        # Generate UUIDs for existing users
        migrations.RunPython(generate_uuid_for_existing_users, migrations.RunPython.noop),
        
        # Now make it non-null, unique
        migrations.AlterField(
            model_name='customuser',
            name='user_id',
            field=models.CharField(max_length=36, editable=False, unique=True),
        ),
    ]
