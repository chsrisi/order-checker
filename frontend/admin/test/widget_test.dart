import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:admin/app_state.dart';
import 'package:admin/main.dart';

void main() {
  testWidgets('Admin Login screen shows', (WidgetTester tester) async {
    dotenv.loadFromString(envString: '''
BASE_URL=http://localhost:8000
WS_URL=ws://localhost:8000
''');
    final appState = AppState();
    // Build our app and trigger a frame.
    await tester.pumpWidget(
      ChangeNotifierProvider<AppState>(
        create: (_) => appState,
        child: const AdminApp(),
      ),
    );

    // Verify that the login screen is shown.
    expect(find.text('Admin Login'), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2)); // Username and Password
    expect(find.text('Login'), findsOneWidget);
  });
}
