// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:frontend/app_state.dart';
import 'package:frontend/main.dart';

import 'package:frontend/models.dart';
import 'package:frontend/screens/orders_view.dart';

void main() {
  testWidgets('Client Login screen shows', (WidgetTester tester) async {
    dotenv.loadFromString(envString: '''
BASE_URL=http://localhost:8000
WS_URL=ws://localhost:8000
''');
    final appState = AppState();
    // Build our app and trigger a frame.
    await tester.pumpWidget(
      ChangeNotifierProvider<AppState>(
        create: (_) => appState,
        child: const MyApp(),
      ),
    );

    // Verify that the login screen is shown.
    expect(find.text('Item Scanner'), findsNWidgets(2));
    expect(find.byType(TextField), findsNWidgets(2)); // Username and Password
    expect(find.text('Login'), findsOneWidget);
  });

  testWidgets('OrdersInputScreen renders scrollable order card with header and items in ListView', (WidgetTester tester) async {
    final appState = AppState();
    appState.orders.add(
      ShopeeOrder(
        orderSn: "240101ABC123",
        status: "READY_TO_SHIP",
        splitUp: false,
        done: false,
        shipBy: DateTime.now(),
        itemList: [
          ShopeeOrderItemBOM(
            componentSku: "SKU-001",
            componentName: "Test Item 1",
            quantity: 2,
            location: "A-01",
          ),
          ShopeeOrderItemBOM(
            componentSku: "SKU-002",
            componentName: "Test Item 2",
            quantity: 1,
            location: "B-02",
          ),
        ],
        info: [
          ShopeeOrderInfo(
            id: 1,
            pickupCode: "PK-12345",
          ),
        ],
        recipientAddress: ShopeeOrderRecipient(
          id: 1,
          name: "John Doe",
          city: "Jakarta",
        ),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChangeNotifierProvider<AppState>.value(
            value: appState,
            child: const OrdersInputScreen(
              selectedOrder: "240101ABC123",
            ),
          ),
        ),
      ),
    );

    // Verify card rendered
    expect(find.byType(Card), findsOneWidget);
    // Verify ListView is inside Card and contains header and items
    expect(find.descendant(of: find.byType(Card), matching: find.byType(ListView)), findsOneWidget);
    expect(find.text("PK-12345"), findsOneWidget);
    expect(find.text("Test Item 1"), findsOneWidget);
    expect(find.text("Test Item 2"), findsOneWidget);
    expect(find.text("Recipient: John Doe (Jakarta)"), findsOneWidget);
  });
}
