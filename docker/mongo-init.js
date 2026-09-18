// MongoDB initialization script for MIRAGE (runs once on fresh volume)
// Creates unprivileged application user mirage_app on mirage_traces database

const traceDbName = "mirage_traces";
const appUser = "mirage_app";
const appPass = "mirage_mongo_secret";

const dbInstance = db.getSiblingDB(traceDbName);

// Check if user already exists
const existingUser = dbInstance.getUser(appUser);
if (!existingUser) {
    dbInstance.createUser({
        user: appUser,
        pwd: appPass,
        roles: [
            { role: "readWrite", db: traceDbName }
        ]
    });
    print(`Created MongoDB application user: ${appUser} on ${traceDbName}`);
} else {
    print(`MongoDB application user ${appUser} already exists.`);
}
