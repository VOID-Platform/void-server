import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../void/.env') });
dotenv.config({ path: path.resolve(process.cwd(), '.env') });

if (!process.env.DATABASE_URL) {
  process.env.DATABASE_URL = 'postgresql://void:voidpass@localhost:5432/void_db?schema=public';
} else {
  process.env.DATABASE_URL = process.env.DATABASE_URL.replace(/:5435\//, ':5432/');
}
